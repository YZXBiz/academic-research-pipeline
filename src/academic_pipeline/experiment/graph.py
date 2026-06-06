"""PydanticAI experiment graph nodes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import PHASE_DIRS, Stage
from academic_pipeline.experiment.agents import agents as _agents
from academic_pipeline.experiment.context_specs import RESULT_ANALYZER_CONTEXT_SPEC
from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.models.experiment import (
    DesignBundle,
    DesignComparison,
    DesignScore,
    ExperimentResults,
    SelectedDesigns,
)
from academic_pipeline.runtime.context import build_context, build_curated_context
from academic_pipeline.runtime.evaluator import run_with_evaluation
from academic_pipeline.runtime.trace_logger import traced_agent_run


logger = logging.getLogger(__name__)


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


_RUBRIC_DESIGN = """\
Evaluate this experiment plan for a peer-reviewed ML paper:

- Relevance (0-10): Does the experiment directly answer the research question?
- Rigor (0-10): Does it include proper baselines, metrics, and statistical tests?
- Feasibility (0-10): Can it run in under 10 minutes with standard Python packages?
- Novelty (0-10): Does it go beyond running default models on toy datasets?
- Reproducibility (0-10): Are datasets public and methods clearly specified?

Score each dimension. PASS if all dimensions >= 7."""

_RUBRIC_ANALYSIS = """\
Evaluate this experiment analysis for depth and quality:

- Interpretation depth (0-10): Does it explain what results MEAN, not just report numbers?
- Domain connection (0-10): Does it connect findings to the field's theoretical framework?
- Baseline comparison (0-10): Does it explain where/why methods agree and differ?
- Honesty (0-10): Does it acknowledge limitations and alternative explanations?
- Reviewer-readiness (0-10): Would this analysis survive peer review challenges?

Score each dimension. PASS if all dimensions >= 7."""


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
            phase=PHASE_DIRS[Stage.EXPERIMENT],
        )
        ctx.state.plan = result.output
        ctx.state.messages.append({"role": "assistant", "content": "Experiment plan created."})
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
            phase=PHASE_DIRS[Stage.EXPERIMENT],
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
                phase=PHASE_DIRS[Stage.EXPERIMENT],
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

        # Phase 1: stage only the highest-scoring design's plan as state.plan;
        # the typed-config experiment path runs it. Phase 2 will fan out to K
        # parallel runs.
        ctx.state.plan = selected[0].design
        logger.info(
            "DesignSelectionNode picked top %d of %d (chosen for run: %s, score=%.2f)",
            k,
            len(bundle.alternatives),
            selected[0].design_id,
            ordered_scores[0].overall_score,
        )
        ctx.state.messages.append({"role": "assistant", "content": f"Selected designs: {selected_ids}"})
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
            phase=PHASE_DIRS[Stage.EXPERIMENT],
        )
        comparison = result.output
        if not isinstance(comparison, DesignComparison):
            raise RuntimeError(f"design_comparator returned {type(comparison).__name__}, expected DesignComparison")
        ctx.state.design_comparison = comparison
        logger.info("DesignComparison produced (chosen=%s)", comparison.chosen_design_id)
        return End("experiment_complete")


@dataclass
class ConfigWriterNode(BaseNode[ExperimentState, PipelineDeps, str]):
    """2026-05-15 cutover: single LLM call fills a typed ExperimentSpec.

    No Python codegen. The agent picks values from enums (algorithms,
    calibration_methods, metrics) and provides dataset metadata. We
    serialize the spec into the workspace's config.yaml, and the
    template-shipped `pipeline.assets.experiment.canonical` chain runs
    it. The whole class of agent-codegen failures (dangling @asset
    deps, wrong import paths, missing pip deps, wrong sklearn API) is
    structurally impossible under this contract.
    """

    async def run(self, ctx: GraphRunContext[ExperimentState, PipelineDeps]) -> DagsterRunNode:  # noqa: D102
        import yaml  # PyYAML, already a project dep

        from academic_pipeline.experiment.template_copier import copy_template_into
        from academic_pipeline.models.experiment_spec import ExperimentSpec

        out_root = (
            Path(getattr(ctx.deps.config, "output_dir", None) or "output")
            / (ctx.state.run_id or "unknown-run")
            / PHASE_DIRS[Stage.EXPERIMENT]
        )
        workspace = out_root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        copy_template_into(workspace)

        plan_json = ctx.state.plan.model_dump_json(indent=2) if ctx.state.plan else "{}"
        rq_json = ctx.state.rq_brief or "{}"
        agent_ctx = f"Topic: {ctx.state.topic}\n\nExperimentPlan:\n{plan_json}\n\nResearch question brief:\n{rq_json}\n"

        result = await traced_agent_run(
            _agents["config_writer"],
            agent_ctx,
            deps=ctx.deps,
            name="config_writer",
            phase=PHASE_DIRS[Stage.EXPERIMENT],
        )
        spec = result.output
        if not isinstance(spec, ExperimentSpec):
            raise RuntimeError(f"config_writer returned {type(spec).__name__}, expected ExperimentSpec")

        mlflow_name = "_".join(ctx.state.topic.lower().split())[:60] or "experiment"
        config_yaml = {
            "schema_version": 1,
            "dataset": {
                "source": spec.dataset.source,
                "files": list(spec.dataset.files),
                "entity_id_column": spec.dataset.entity_id_column,
                "date_column": None,
                "target_column_patterns": list(spec.dataset.target_column_patterns),
            },
            "mlflow": {"experiment_name": mlflow_name},
            "reproducibility": {"random_seed": spec.random_seed},
            "experiment_spec": {
                "algorithms": [a.value for a in spec.algorithms],
                "calibration_methods": [c.value for c in spec.calibration_methods],
                "metrics": [m.value for m in spec.metrics],
                "random_seed": spec.random_seed,
                "time_limit_s": spec.time_limit_s,
            },
        }
        (workspace / "config.yaml").write_text(yaml.safe_dump(config_yaml, sort_keys=False))

        ctx.state.messages.append(
            {
                "role": "system",
                "content": (
                    f"config_writer wrote config.yaml: algos={[a.value for a in spec.algorithms]} "
                    f"cals={[c.value for c in spec.calibration_methods]} "
                    f"metrics={[m.value for m in spec.metrics]}"
                ),
            }
        )
        logger.info(
            "config_writer wrote spec: algos=%s cals=%s metrics=%s",
            [a.value for a in spec.algorithms],
            [c.value for c in spec.calibration_methods],
            [m.value for m in spec.metrics],
        )
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
            phase=PHASE_DIRS[Stage.EXPERIMENT],
        )
        ctx.state.analysis = result.output
        ctx.state.messages.append({"role": "assistant", "content": "Analysis complete."})
        if ctx.state.design_bundle is not None:
            return DesignComparisonNode()
        return End("experiment_complete")


def build_experiment_graph() -> Graph:
    """Build the experiment subgraph (v2.4 + Spec 7 exploration breadth).

    Default routing:       Design -> ConfigWriter -> DagsterRun -> Analysis -> End
    Bundle path (flag on): Design -> Bundle -> Selection -> ConfigWriter
                           -> DagsterRun -> Analysis -> Comparison -> End
    """
    return Graph(  # pyright: ignore[reportReturnType]
        name="experiment",
        nodes=[
            ExperimentDesignNode,
            ExperimentDesignBundleNode,
            DesignSelectionNode,
            ConfigWriterNode,
            DagsterRunNode,
            AnalysisNode,
            DesignComparisonNode,
        ],
    )
