"""PydanticAI experiment graph nodes."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.experiment.agents import agents as _agents
from academic_pipeline.experiment.context_specs import RESULT_ANALYZER_CONTEXT_SPEC
from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.models.experiment import (
    DesignBundle,
    DesignComparison,
    DesignScore,
    ExperimentResults,
    FigureArtifact,
    SelectedDesigns,
    StatisticalTest,
)
from academic_pipeline.runtime.context import build_context, build_curated_context
from academic_pipeline.runtime.evaluator import run_with_evaluation
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.tools.agent_cache import AgentMessageCache


logger = logging.getLogger(__name__)

_DEBUG_DIR = "experiment_debug"


def _dump_debug(code: str, exec_result: object) -> None:
    """Dump generated script + execution output to files for debugging."""
    import os

    os.makedirs(_DEBUG_DIR, exist_ok=True)
    count = len([f for f in os.listdir(_DEBUG_DIR) if f.startswith("script_")])
    prefix = f"{_DEBUG_DIR}/attempt_{count + 1}"

    with open(f"{prefix}_script.py", "w") as f:
        f.write(code)
    with open(f"{prefix}_error.txt", "w") as f:
        f.write(f"error: {getattr(exec_result, 'error', 'N/A')}\n\n")
        f.write(f"=== STDOUT ===\n{getattr(exec_result, 'stdout', '')}\n\n")
        f.write(f"=== STDERR ===\n{getattr(exec_result, 'stderr', '')}\n")

    logger.info("Debug dump saved to %s_script.py and %s_error.txt", prefix, prefix)


def strip_code_fences(code: str) -> str:
    """Extract Python code from markdown-fenced LLM output.

    Handles both 'starts with fence' and 'preamble text before fence' cases.
    If multiple fenced blocks exist, extracts the longest one.
    """
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", code, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()

    code = code.strip()
    if code.startswith("```python"):
        code = code[len("```python") :].strip()
    if code.startswith("```"):
        code = code[3:].strip()
    if code.endswith("```"):
        code = code[:-3].strip()
    return code


def _strip_markdown_fences(text: str) -> str:
    """Strip ```yaml / ``` markdown code fences from LLM output.

    LLMs frequently wrap structured-output strings in markdown fences even
    when the output schema is plain str. The Dagster workspace's YAML
    loader fails with ``ScannerError`` on the leading backticks. Strip them
    surgically — only outer fences, no regex scan that could damage backtick
    characters appearing inside the YAML body.
    """
    text = text.strip()
    if text.startswith("```yaml"):
        text = text[len("```yaml") :]
    elif text.startswith("```yml"):
        text = text[len("```yml") :]
    elif text.startswith("```"):
        text = text[3:]
    text = text.lstrip("\n").rstrip()
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text


def _parse_stat_tests(raw: dict) -> dict[str, StatisticalTest]:
    """Parse raw statistical test dicts into StatisticalTest models."""
    result: dict[str, StatisticalTest] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            result[k] = StatisticalTest(
                test_name=v.get("test_name", "unknown"),
                p_value=v.get("p_value", 1.0),
                significant=v.get("significant", False),
                effect_size=v.get("effect_size"),
            )
    return result


_RUBRIC_DESIGN = """\
Evaluate this experiment plan for a peer-reviewed ML paper:

- Relevance (0-10): Does the experiment directly answer the research question?
- Rigor (0-10): Does it include proper baselines, metrics, and statistical tests?
- Feasibility (0-10): Can it run in under 10 minutes with standard Python packages?
- Novelty (0-10): Does it go beyond running default models on toy datasets?
- Reproducibility (0-10): Are datasets public and methods clearly specified?

Score each dimension. PASS if all dimensions >= 7."""

_RUBRIC_CODE = """\
Evaluate this experiment code for correctness and completeness:

- Correctness (0-10): Will the code run without errors?
- Completeness (0-10): Does it implement ALL parts of the experiment plan?
- Statistical rigor (0-10): Does it include k-fold CV, significance tests, and CIs?
- Figure quality (0-10): Does it generate all required figures?
- Output contract (0-10): Does it save valid results.json with the required schema?

Score each dimension. PASS if all dimensions >= 7."""

_RUBRIC_ANALYSIS = """\
Evaluate this experiment analysis for depth and quality:

- Interpretation depth (0-10): Does it explain what results MEAN, not just report numbers?
- Domain connection (0-10): Does it connect findings to the field's theoretical framework?
- Baseline comparison (0-10): Does it explain where/why methods agree and differ?
- Honesty (0-10): Does it acknowledge limitations and alternative explanations?
- Reviewer-readiness (0-10): Would this analysis survive peer review challenges?

Score each dimension. PASS if all dimensions >= 7."""

_RUBRIC_IMPROVEMENT = """\
Compare the improved experiment against the previous version:

- Metric improvement (0-10): Did the primary metric improve?
- Scientific value (0-10): Does the change add insight to the paper?
- No regression (0-10): Did other metrics stay stable?

Score each dimension. PASS if improvement is genuine."""


@dataclass
class ExperimentDesignNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """Design the experiment plan from research outputs.

    When ``config.exploration_breadth_enabled`` is True this node delegates to
    ``ExperimentDesignBundleNode`` instead of producing a single design. The
    bundle path produces N alternatives, scores each, and selects top K.
    """

    async def run(
        self, ctx: GraphRunContext[ExperimentState, PipelineDeps]
    ) -> ConfigWriterNode | ExperimentDesignBundleNode:
        """Design experiment from research outputs and produce a plan."""
        if ctx.deps.config.exploration_breadth_enabled:
            logger.info("Exploration breadth flag on — routing to ExperimentDesignBundleNode")
            return ExperimentDesignBundleNode()

        context = build_context(
            ctx.state,
            ["topic", "rq_brief", "methodology_blueprint", "synthesis"],
            node_name="ExperimentDesignNode",
        )
        result = await run_with_evaluation(
            agent=_agents["experiment_designer"],
            context=context,
            rubric=_RUBRIC_DESIGN,
            deps=ctx.deps,
            name="experiment_designer",
            phase="02-experiment",
        )
        ctx.state.plan = result.output
        ctx.state.messages.append({"role": "assistant", "content": "Experiment plan created."})
        # v2 (Phase 2): replaces InteractiveMLNode with ConfigWriter → DagsterRun
        return ConfigWriterNode()


@dataclass
class ExperimentDesignBundleNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """Produce N candidate experiment designs (Spec 7, exploration breadth).

    Only invoked when ``config.exploration_breadth_enabled`` is True. The
    output ``DesignBundle`` is stored on state and routed to
    ``DesignSelectionNode`` for scoring and top-K selection.
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> DesignSelectionNode:
        """Produce a DesignBundle of N alternatives via the bundle agent."""
        context = build_context(
            ctx.state,
            ["topic", "rq_brief", "methodology_blueprint", "synthesis"],
            node_name="ExperimentDesignBundleNode",
        )
        n = ctx.deps.config.n_design_alternatives
        context = (
            f"{context}\n\n"
            f"Produce exactly N={n} diverse design alternatives in the bundle. "
            "Method families across the alternatives must be diverse — see the "
            "diversity constraint in your instructions."
        )
        result = await traced_agent_run(
            _agents["experiment_designer_bundle"],
            context,
            deps=ctx.deps,
            name="experiment_designer_bundle",
            phase="02-experiment",
        )
        bundle = result.output
        if not isinstance(bundle, DesignBundle):
            raise RuntimeError(f"experiment_designer_bundle returned {type(bundle).__name__}, expected DesignBundle")
        ctx.state.design_bundle = bundle
        logger.info(
            "DesignBundle produced with %d alternatives: %s",
            len(bundle.alternatives),
            [a.design_id for a in bundle.alternatives],
        )
        ctx.state.messages.append(
            {"role": "assistant", "content": f"Design bundle with {len(bundle.alternatives)} alternatives."}
        )
        return DesignSelectionNode()


@dataclass
class DesignSelectionNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """Score every DesignAlternative and select the top K (Spec 7).

    Phase 1 simplification: even with K>=2, only the SINGLE highest-scoring
    design is actually executed downstream (its plan is set on state.plan).
    Phase 2 will fan out to K parallel runs.
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> ConfigWriterNode:
        """Score every alternative, select top K, and stage the chosen plan."""
        bundle = ctx.state.design_bundle
        if bundle is None or not bundle.alternatives:
            raise RuntimeError("DesignSelectionNode requires state.design_bundle with alternatives")

        scores: list[DesignScore] = []
        for alt in bundle.alternatives:
            ctx_text = (
                f"Research topic: {ctx.state.topic}\n\n"
                f"Research question brief: {ctx.state.rq_brief}\n\n"
                f"DesignAlternative to score (design_id={alt.design_id}):\n"
                f"{alt.model_dump_json(indent=2)}"
            )
            score_result = await traced_agent_run(
                _agents["design_scorer"],
                ctx_text,
                deps=ctx.deps,
                name="design_scorer",
                phase="02-experiment",
            )
            score_out = score_result.output
            if not isinstance(score_out, DesignScore):
                raise RuntimeError(f"design_scorer returned {type(score_out).__name__}, expected DesignScore")
            scores.append(score_out)

        # Sort: highest overall_score first; preserve bundle order on ties
        id_to_alt = {a.design_id: a for a in bundle.alternatives}
        ordered_scores = sorted(scores, key=lambda s: -s.overall_score)
        k = min(ctx.deps.config.k_designs_to_run, len(bundle.alternatives))
        selected_ids = [s.design_id for s in ordered_scores[:k]]
        selected = [id_to_alt[i] for i in selected_ids if i in id_to_alt]
        not_selected_ids = [s.design_id for s in ordered_scores[k:]]
        not_selected = [id_to_alt[i] for i in not_selected_ids if i in id_to_alt]

        ctx.state.selected_designs = SelectedDesigns(
            selected=selected,
            not_selected=not_selected,
            scores=scores,
        )

        # Phase 1: stage only the highest-scoring design's plan as state.plan
        # so the existing InteractiveMLNode runs unchanged. Phase 2 will fan
        # out to K parallel runs.
        ctx.state.plan = selected[0].design
        logger.info(
            "DesignSelectionNode picked top %d of %d (chosen for run: %s, score=%.2f)",
            k,
            len(bundle.alternatives),
            selected[0].design_id,
            ordered_scores[0].overall_score,
        )
        ctx.state.messages.append({"role": "assistant", "content": f"Selected designs: {selected_ids}"})
        # v2 (Phase 2): replaces InteractiveMLNode with ConfigWriter → DagsterRun
        return ConfigWriterNode()


@dataclass
class DesignComparisonNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """Produce a DesignComparison artifact for the paper's Discussion section.

    Phase 1: only the chosen design has results; the comparison table names
    the alternatives and marks unrun rows as "deferred (Phase 1)".
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> End[str]:
        """Produce DesignComparison and end the subgraph."""
        selected = ctx.state.selected_designs
        if selected is None or not selected.selected:
            raise RuntimeError("DesignComparisonNode requires state.selected_designs to be populated")
        chosen = selected.selected[0]
        if ctx.state.results is None:
            raise RuntimeError("DesignComparisonNode requires state.results to be populated")
        selected_results: dict[str, ExperimentResults] = {chosen.design_id: ctx.state.results}

        ctx_text = (
            f"SelectedDesigns metadata:\n{selected.model_dump_json(indent=2)}\n\n"
            f"Per-design results (Phase 1: only the chosen design has results):\n"
            + "\n".join(f"  {did}: {res.model_dump_json()}" for did, res in selected_results.items())
            + "\n\nProduce a DesignComparison whose chosen_design_id is "
            f"{chosen.design_id}."
        )
        result = await traced_agent_run(
            _agents["design_comparator"],
            ctx_text,
            deps=ctx.deps,
            name="design_comparator",
            phase="02-experiment",
        )
        comparison = result.output
        if not isinstance(comparison, DesignComparison):
            raise RuntimeError(f"design_comparator returned {type(comparison).__name__}, expected DesignComparison")
        ctx.state.design_comparison = comparison
        logger.info("DesignComparison produced (chosen=%s)", comparison.chosen_design_id)
        return End("experiment_complete")


def _collect_experiment_artifacts(env, state, output_dir):
    """Collect experiment artifacts from Docker volume into structured output directory."""
    from academic_pipeline.experiment.report import generate_experiment_report

    artifacts_dir = output_dir / "artifacts"
    code_dir = output_dir / "code"
    figures_dir = output_dir / "figures"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    local = Path(env.local_workplace)

    # Copy results.json
    src = local / "results.json"
    if src.exists():
        shutil.copy2(src, artifacts_dir / "results.json")

    # Save experiment plan
    if state.plan:
        (artifacts_dir / "experiment_plan.json").write_text(state.plan.model_dump_json(indent=2))

    # Auto-generate dataset_info.json from plan
    if state.plan and state.plan.dataset_sources:
        ds_info = [ds.model_dump() for ds in state.plan.dataset_sources]
        (artifacts_dir / "dataset_info.json").write_text(json.dumps(ds_info, indent=2))

    # Copy figures
    src_figs = local / "figures"
    if src_figs.exists():
        for fig in src_figs.glob("*.png"):
            shutil.copy2(fig, figures_dir / fig.name)

    # Copy all code files from workspace
    for py_file in local.glob("*.py"):
        shutil.copy2(py_file, code_dir / py_file.name)

    # Generate reproducibility.json
    repro = {
        "seeds": [42, 123, 456],
        "autogluon_presets": "medium_quality",
        "autogluon_time_limit": 300,
        "timestamp": datetime.now(UTC).isoformat(),
        "pipeline_version": "2.4.0",
        "predictor_type": state.predictor_type,
    }
    ver = env.run_command("pip show autogluon 2>/dev/null | grep Version | cut -d' ' -f2")
    if ver["status"] == 0:
        repro["autogluon_version"] = ver["result"].strip()
    pyver = env.run_command("python --version 2>&1 | cut -d' ' -f2")
    if pyver["status"] == 0:
        repro["python_version"] = pyver["result"].strip()
    if state.plan and state.plan.dataset_sources:
        ds = state.plan.dataset_sources[0]
        repro["dataset"] = {"name": ds.name, "source": ds.source, "target": ds.target_column}
    (artifacts_dir / "reproducibility.json").write_text(json.dumps(repro, indent=2))

    # Generate HTML report
    generate_experiment_report(output_dir)


@dataclass
class InteractiveMLNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """DEPRECATED — replaced by ConfigWriterNode + DagsterRunNode (Phase 2 cutover, 2026-05-04).

    Class kept so pre-cutover snapshots still deserialize. `.run()` raises with
    a redirect message so users know they need to start a fresh run.
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> JudgeNode | End[str]:  # noqa: ARG002, D102
        raise RuntimeError(
            "InteractiveMLNode is deprecated. The experiment phase has been replaced by "
            "ConfigWriterNode + DagsterRunNode (Phase 2 cutover 2026-05-04). Pre-cutover "
            "runs cannot resume; start a fresh run with `make run-experiment TOPIC=...`."
        )

    async def _legacy_run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> JudgeNode | End[str]:
        """Original implementation, retained for reference only — not invoked."""
        from academic_pipeline.models.experiment_output import ExperimentFailed
        from academic_pipeline.tools.execution.docker_env import DockerConfig, DockerEnv

        # 1. Start persistent Docker container
        if ctx.deps.docker_env is not None:
            env = ctx.deps.docker_env
        else:
            run_id = str(uuid.uuid4())[:8]
            if ctx.deps.trace_logger:
                local_root = str((ctx.deps.trace_logger.output_dir / "02-experiment").resolve())
            else:
                local_root = os.getcwd()
            config = DockerConfig(
                container_name=f"experiment-{run_id}",
                local_root=local_root,
            )
            env = DockerEnv(config)
            env.init_container()
            ctx.deps.docker_env = env

        # 1b. Set up message cache for conversation resume
        trace_logger = ctx.deps.trace_logger
        if trace_logger:
            cache_dir = str(trace_logger.output_dir / "02-experiment" / "cache")
        else:
            cache_dir = str(Path("output/latest/02-experiment/cache").resolve())
        cache = AgentMessageCache(cache_dir=cache_dir, agent_name="ml_engineer")
        prior_messages = cache.load()

        # 2. Build context from experiment plan + judge feedback
        plan_json = ctx.state.plan.model_dump_json(indent=2) if ctx.state.plan else "{}"
        context_parts = [f"Experiment Plan:\n{plan_json}"]
        if ctx.state.judge_feedback:
            context_parts.append(f"\n\nJudge Feedback (address these issues):\n{ctx.state.judge_feedback}")
        if ctx.state.judge_further_experiments:
            further = "\n".join(f"- {e}" for e in ctx.state.judge_further_experiments)
            context_parts.append(f"\n\nFurther Experiments to Run:\n{further}")
        context = "\n".join(context_parts)

        # 3. Run ML agent
        try:
            result = await traced_agent_run(
                _agents["ml_engineer"],
                context,
                deps=ctx.deps,
                name="ml_engineer",
                phase="02-experiment",
                message_history=prior_messages,
            )
        except Exception as e:
            logger.error("ML engineer agent failed: %s", e)
            env.stop_container()
            return End("agent_failed")

        # 3b. Save conversation for judge loop resume / crash recovery
        try:
            cache.save(result.all_messages_json())
        except Exception as e:
            logger.warning("Failed to save agent message cache: %s", e)

        # 4. Handle result
        output = result.output
        if isinstance(output, ExperimentFailed):
            logger.warning("ML engineer gave up: %s", output.failure_reason)
            env.stop_container()
            ctx.state.error_history.append(f"Agent gave up: {output.failure_reason}")
            return End("experiment_failed")

        # 5. Collect results from mounted volume
        results_path = Path(env.local_workplace) / "results.json"
        if results_path.exists():
            try:
                results_data = json.loads(results_path.read_text())
                figures: list[FigureArtifact] = []
                figures_dir = Path(env.local_workplace) / "figures"
                if figures_dir.exists():
                    for fig_path in sorted(figures_dir.glob("*.png")):
                        fig_data = base64.b64encode(fig_path.read_bytes()).decode()
                        figures.append(
                            FigureArtifact(
                                figure_type=fig_path.stem.replace("fig_", ""),
                                filename=fig_path.name,
                                caption=fig_path.stem.replace("_", " ").title(),
                                data_base64=fig_data,
                            )
                        )

                ctx.state.results = ExperimentResults(
                    success=True,
                    metrics=results_data.get("metrics", {}),
                    cv_scores=results_data.get("cv_scores", {}),
                    statistical_tests=_parse_stat_tests(results_data.get("statistical_tests", {})),
                    figures=figures,
                    stdout=getattr(output, "results_summary", ""),
                    stderr="",
                    code="interactive_session",
                )
                ctx.state.generated_code = "interactive_session"
                logger.info(
                    "Experiment completed: %d metrics, %d figures",
                    len(results_data.get("metrics", {})),
                    len(figures),
                )
            except Exception as e:
                logger.error("Failed to parse results: %s", e)
                env.stop_container()
                return End("parse_failed")
        else:
            logger.warning("No results.json found after ML agent completed")
            env.stop_container()
            return End("no_results")

        # 6. Collect artifacts into structured output directory
        try:
            experiment_output_dir = Path("output") / "latest" / "02-experiment"
            experiment_output_dir.mkdir(parents=True, exist_ok=True)
            _collect_experiment_artifacts(env, ctx.state, experiment_output_dir)
        except Exception as e:
            logger.warning("Artifact collection failed: %s", e)

        # Container stays alive for judge inspection
        return JudgeNode()


@dataclass
class JudgeNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """DEPRECATED — replaced by Dagster asset_check on results.json (Phase 2 cutover, 2026-05-04).

    Class kept so pre-cutover snapshots still deserialize. `.run()` raises with
    a redirect message.
    """

    async def run(  # noqa: D102
        self,
        ctx: GraphRunContext[ExperimentState, PipelineDeps],  # noqa: ARG002
    ) -> InteractiveMLNode | AnalysisNode | End[str]:
        raise RuntimeError(
            "JudgeNode is deprecated. Result evaluation now happens via a Dagster "
            "asset_check on results.json (Phase 2 cutover 2026-05-04). Pre-cutover "
            "runs cannot resume; start a fresh run."
        )

    async def _legacy_run(
        self, ctx: GraphRunContext[ExperimentState, PipelineDeps]
    ) -> InteractiveMLNode | AnalysisNode | End[str]:
        """Original implementation, retained for reference only — not invoked."""
        from academic_pipeline.models.experiment_output import JudgeVerdict

        plan_json = ctx.state.plan.model_dump_json(indent=2) if ctx.state.plan else "{}"
        results_json = ctx.state.results.model_dump_json(indent=2) if ctx.state.results else "{}"

        context = (
            f"Experiment Plan:\n{plan_json}\n\n"
            f"Results:\n{results_json}\n\n"
            "Evaluate the implementation. Use read_file, list_files, gen_code_tree, "
            "execute_command, and visualize_figure to inspect the actual code and figures "
            "in /workspace."
        )

        try:
            result = await traced_agent_run(
                _agents["experiment_judge"],
                context,
                deps=ctx.deps,
                name="experiment_judge",
                phase="02-experiment",
            )
        except Exception as e:
            logger.error("Judge agent failed: %s", e)
            # On judge failure, accept current results
            if ctx.deps.docker_env:
                ctx.deps.docker_env.stop_container()
            return AnalysisNode()

        verdict = result.output
        if isinstance(verdict, JudgeVerdict):
            # Save judge verdict as artifact
            try:
                judge_artifacts = Path("output") / "latest" / "02-experiment" / "artifacts"
                judge_artifacts.mkdir(parents=True, exist_ok=True)
                (judge_artifacts / "judge_verdict.json").write_text(verdict.model_dump_json(indent=2))
            except Exception as e:
                logger.warning("Failed to save judge verdict: %s", e)

            if verdict.verdict == "APPROVED":
                logger.info("Judge approved experiment")
                if ctx.deps.docker_env:
                    ctx.deps.docker_env.stop_container()
                return AnalysisNode()

            # MODIFY — loop back
            ctx.state.judge_iteration += 1
            if ctx.state.judge_iteration >= 2:
                logger.warning("Judge loop max iterations — accepting current results")
                if ctx.deps.docker_env:
                    ctx.deps.docker_env.stop_container()
                return AnalysisNode()

            ctx.state.judge_feedback = "\n".join(verdict.suggestions)
            ctx.state.judge_further_experiments = list(verdict.further_experiments)
            logger.info("Judge requests modifications (iter %d/2): %s", ctx.state.judge_iteration, verdict.suggestions)
            return InteractiveMLNode()

        # Fallback — accept results
        if ctx.deps.docker_env:
            ctx.deps.docker_env.stop_container()
        return AnalysisNode()


@dataclass
class ConfigWriterNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """v2: single LLM call generates the entire experiment workspace.

    The agent emits a WorkspaceFiles bundle: orchestration config.yaml plus
    N Python @asset modules under src/pipeline/assets/experiment/. The
    template provides the Dagster scaffold (resources, data_load, package
    init); the agent fills in ALL the ML logic.
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> DagsterRunNode:  # noqa: D102
        from academic_pipeline.experiment.template_copier import copy_template_into
        from academic_pipeline.models.experiment import WorkspaceFiles

        out_root = (
            Path(getattr(ctx.deps.config, "output_dir", None) or "output")
            / (ctx.state.run_id or "unknown-run")
            / "02-experiment"
        )
        workspace = out_root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        copy_template_into(workspace)

        plan_json = ctx.state.plan.model_dump_json(indent=2) if ctx.state.plan else "{}"
        rq_json = ctx.state.rq_brief or "{}"
        agent_ctx = (
            f"Topic: {ctx.state.topic}\n\n"
            f"ExperimentPlan:\n{plan_json}\n\n"
            f"Research question brief:\n{rq_json}\n\n"
            f"Workspace path: {workspace}\n"
        )

        result = await traced_agent_run(
            _agents["config_writer"],
            agent_ctx,
            deps=ctx.deps,
            name="config_writer",
            phase="02-experiment",
        )
        bundle = result.output
        if not isinstance(bundle, WorkspaceFiles):
            raise RuntimeError(f"config_writer returned {type(bundle).__name__}, expected WorkspaceFiles")

        written: list[str] = []
        for f in bundle.files:
            target = workspace / f.path
            if not str(target.resolve()).startswith(str(workspace.resolve())):
                raise RuntimeError(f"config_writer attempted to write outside workspace: {f.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_strip_markdown_fences(f.content))
            written.append(str(target.relative_to(workspace)))

        if not any(p == "config.yaml" for p in written):
            raise RuntimeError(f"config_writer did not produce config.yaml (got: {written})")
        ctx.state.messages.append(
            {
                "role": "system",
                "content": f"config_writer wrote {len(written)} files: {', '.join(written)}",
            }
        )
        logger.info("config_writer wrote %d files into %s", len(written), workspace)
        return DagsterRunNode(workspace=workspace)


@dataclass
class DagsterRunNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """v2 (Phase 2): runs `dagster job execute` against workspace as subprocess.

    No LLM. On failure, populates error_history and routes to AnalysisNode with
    empty results — AnalysisNode handles the no-results case gracefully.
    """

    workspace: Path

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> AnalysisNode:  # noqa: D102
        from academic_pipeline.experiment.dagster_runner import (
            load_results_json,
            run_dagster_job,
        )

        timeout_s = getattr(ctx.deps.config, "experiment_timeout_s", 1800)
        result = run_dagster_job(self.workspace, timeout_s=timeout_s)
        if not result.succeeded:
            ctx.state.error_history.append(f"Dagster run failed (rc={result.returncode}): {result.stderr[-1500:]}")
            ctx.state.results = None
            ctx.state.analysis = None
            return AnalysisNode()

        results = load_results_json(result.results_json_path)
        # Wrap whatever the LLM-generated results.json contains. ExperimentResults
        # has extra="allow" so raw_results / summary / figures land as extras while
        # the legacy required `metrics` field gets a safe empty default. Downstream
        # result_analyzer reads raw_results as the source of truth — the agent is
        # free to design any results.json schema it wants.
        from academic_pipeline.models.experiment import ExperimentResults

        ctx.state.results = ExperimentResults.model_validate(
            {
                "metrics": {},
                "raw_results": results,
                "summary": _summarize_results(results),
                "figures": _list_figures(self.workspace / "figures"),
            }
        )
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Dagster job complete; results.json + figures available.",
            }
        )
        return AnalysisNode()


def _summarize_results(results: dict) -> str:
    """Generic summary of an LLM-generated results.json.

    Walks the top-level dict and reports key shapes (length for lists,
    truncated value for scalars). Avoids hardcoding any specific schema —
    the agent is free to design results.json however it wants.
    """
    lines: list[str] = []
    for key, val in results.items():
        if isinstance(val, list):
            lines.append(f"{key}: list[{len(val)}]")
        elif isinstance(val, dict):
            lines.append(f"{key}: dict({len(val)} keys: {', '.join(list(val)[:5])})")
        else:
            preview = str(val)
            lines.append(f"{key}: {preview[:80]}")
    return "\n".join(lines) if lines else "(empty results.json)"


def _list_figures(figures_dir: Path) -> list[str]:
    if not figures_dir.exists():
        return []
    return sorted(str(p) for p in figures_dir.glob("*.png"))


@dataclass
class AnalysisNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """Interpret experiment results with domain-theoretic depth."""

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> DesignComparisonNode | End[str]:
        """Interpret experiment results with domain-theoretic depth.

        When the exploration-breadth bundle path was used (state.design_bundle
        populated), routes to DesignComparisonNode to emit the cross-design
        comparison artifact. Otherwise ends the subgraph as before.
        """
        # Per-agent ContextSpec rollout (PRD §6.10.T3). Curated context
        # exposes topic + rq_brief + synthesis + results plus the full
        # numerical_store so the analyzer can cite raw experiment numbers.
        curated = build_curated_context(ctx.state, RESULT_ANALYZER_CONTEXT_SPEC)
        context = f"{curated}\n\nAnalyze these experiment results for a peer-reviewed paper."
        result = await run_with_evaluation(
            agent=_agents["result_analyzer"],
            context=context,
            rubric=_RUBRIC_ANALYSIS,
            deps=ctx.deps,
            name="result_analyzer",
            phase="02-experiment",
        )
        ctx.state.analysis = result.output
        ctx.state.messages.append({"role": "assistant", "content": "Analysis complete."})
        if ctx.state.design_bundle is not None:
            return DesignComparisonNode()
        return End("experiment_complete")


def build_experiment_graph() -> Graph:
    """Build the experiment subgraph (v2.4 + Spec 7 exploration breadth).

    Default routing (flag off): Design -> InteractiveML -> Judge -> Analysis -> End
    Bundle path (flag on):     Design -> Bundle -> Selection -> InteractiveML
                               -> Judge -> Analysis -> Comparison -> End
    """
    return Graph(  # pyright: ignore[reportReturnType]
        name="experiment",
        nodes=[
            ExperimentDesignNode,
            ExperimentDesignBundleNode,
            DesignSelectionNode,
            ConfigWriterNode,  # v2 (Phase 2): replaces InteractiveML loop
            DagsterRunNode,  # v2 (Phase 2): subprocess Dagster runner
            AnalysisNode,
            DesignComparisonNode,
            # Kept for snapshot-deserialization compat with pre-cutover runs.
            # Both raise on .run() to redirect users to a fresh run.
            InteractiveMLNode,
            JudgeNode,
        ],
    )
