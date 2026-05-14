"""PydanticAI pipeline orchestrator nodes.

Eleven node dataclasses forming the pipeline orchestrator graph: intake,
research phase, write phase, pre-integrity check, integrity fix loop,
review phase (read-only), final integrity, final integrity fix,
finalize, summary, and abort.

Each orchestrator node invokes a subgraph by building it, running it,
and merging results back into the pipeline state.  The writing subgraph
handles per-node evaluation internally, so no global revision loop is
needed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import (
    PipelineStatus,
    Stage,
    Verdict,
)
from academic_pipeline.experiment.agents import agents as _experiment_agents
from academic_pipeline.experiment.graph import (
    ExperimentDesignNode as ExperimentEntryNode,
)
from academic_pipeline.experiment.graph import (
    build_experiment_graph,
)
from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.integrity.graph import IntegrityCheckNode, build_integrity_graph
from academic_pipeline.integrity.state import IntegrityState
from academic_pipeline.models.experiment import FigureArtifact
from academic_pipeline.models.integrity import MaterialPassport
from academic_pipeline.persistence import SqliteStatePersistence
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.research.graph import ResearchQuestionNode, build_research_graph
from academic_pipeline.research.state import ResearchState
from academic_pipeline.review.graph import FieldAnalystNode, build_review_graph
from academic_pipeline.review.state import ReviewState
from academic_pipeline.runtime.context import build_context
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.writing.graph import (
    IntakeNode as WritingIntakeNode,
)
from academic_pipeline.writing.graph import build_writing_graph
from academic_pipeline.writing.state import WritingState


logger = logging.getLogger(__name__)

_PERSISTENCE_DIR = Path(".pipeline_runs")


async def _run_subgraph_with_persistence(
    graph: Graph,
    start_node: BaseNode,
    state: object,
    deps: PipelineDeps,
    run_id: str,
    subgraph_name: str,
    pipeline_state: PipelineState | None = None,
    pipeline_ref: object | None = None,
) -> object:
    """Run a subgraph with SQLite persistence and per-node dashboard updates.

    Uses graph.iter() / graph.iter_from_persistence() to get per-node callbacks,
    enabling dashboard updates during subgraph execution.

    On first run: iterates from start_node, snapshots every node, returns the
    same state object (mutated in place by nodes).

    On resume (after crash): loads last snapshot and resumes from there. Returns
    the state loaded from snapshots — DIFFERENT object than the `state` arg,
    which is ignored on resume. Callers must use the returned state, not the
    one they passed in.
    """
    persistence_dir = deps.persistence_dir or _PERSISTENCE_DIR
    persistence = SqliteStatePersistence(
        db_path=persistence_dir / "pipeline.sqlite",
        run_id=f"{run_id}_{subgraph_name}",
    )

    can_resume = await persistence.can_resume()
    if can_resume:
        # If the subgraph already ran to completion (end snapshot status=success
        # with no created NodeSnapshots remaining), iter_from_persistence would
        # raise "Unable to restore snapshot from state persistence" because
        # load_next() only returns created NodeSnapshots, not EndSnapshots.
        # Detect this case and return the final state directly from the end
        # snapshot — happens when the subgraph completed but the OUTER pipeline
        # body crashed AFTER the subgraph returned (e.g. on a downstream
        # NameError), leaving the OUTER snapshot 'error' but the subgraph
        # fully sealed.
        from pydantic_graph.persistence import EndSnapshot, NodeSnapshot

        # Type adapter must be set before load_all() can deserialize. Normally
        # pydantic_graph sets it inside iter_from_persistence via set_graph_types;
        # we need it earlier here to peek at the existing snapshots.
        if persistence.should_set_types():
            persistence.set_graph_types(graph)

        all_snaps = await persistence.load_all()
        has_created_node = any(isinstance(s, NodeSnapshot) and s.status == "created" for s in all_snaps)
        # EndSnapshot has no status field — its existence is the completion marker.
        completed_end = next(
            (s for s in all_snaps if isinstance(s, EndSnapshot)),
            None,
        )
        if completed_end is not None and not has_created_node:
            logger.info(
                "%s subgraph already complete — returning final state from end snapshot " "(run_id=%s_%s)",
                subgraph_name,
                run_id,
                subgraph_name,
            )
            return completed_end.state

        logger.info("Resuming %s subgraph from last checkpoint (run_id=%s_%s)", subgraph_name, run_id, subgraph_name)
        await persistence.reset_crashed_snapshots()
        async with graph.iter_from_persistence(persistence, deps=deps) as run:  # pyright: ignore[reportArgumentType]
            async for node in run:
                await _on_subgraph_node_complete(
                    node,
                    subgraph_name,
                    pipeline_state,
                    pipeline_ref=pipeline_ref,
                )
            return run.state  # pyright: ignore[reportAttributeAccessIssue]
    else:
        async with graph.iter(start_node, state=state, deps=deps, persistence=persistence) as run:  # pyright: ignore[reportArgumentType]
            async for node in run:
                await _on_subgraph_node_complete(
                    node,
                    subgraph_name,
                    pipeline_state,
                    pipeline_ref=pipeline_ref,
                )
            return run.state  # pyright: ignore[reportAttributeAccessIssue]


async def _on_subgraph_node_complete(
    node: object,
    subgraph_name: str,
    pipeline_state: PipelineState | None,
    *,
    pipeline_ref: object | None = None,
) -> None:
    """Update pipeline state and emit events for a completed subgraph node."""
    import time as _time

    node_name = type(node).__name__
    logger.info("[%s] %s completed", subgraph_name, node_name)

    if pipeline_state is None:
        return

    current_stage = str(pipeline_state.current_stage) if pipeline_state.current_stage else ""

    # Production always supplies a Pipeline as pipeline_ref. Route through
    # _emit_and_apply so disk + in-memory state advance together.
    if pipeline_ref is None:
        return

    last_stage: str = getattr(pipeline_ref, "_last_stage", "")
    if current_stage and current_stage != last_stage:
        await pipeline_ref._emit_and_apply(  # type: ignore[attr-defined]
            "stage_change",
            stage=current_stage,
            previous=last_stage or None,
        )
        pipeline_ref._last_stage = current_stage  # type: ignore[attr-defined]

    last_t: float = getattr(pipeline_ref, "_last_node_t", 0.0)
    now = _time.monotonic()
    duration_s = max(0.0, now - last_t) if last_t else 0.0
    pipeline_ref._last_node_t = now  # type: ignore[attr-defined]

    await pipeline_ref._emit_and_apply(  # type: ignore[attr-defined]
        "node_complete",
        stage=current_stage,
        node=node_name,
        scope="subgraph",
        duration_s=duration_s,
    )


@dataclass
class IntakeNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Initialize the pipeline run and route to the novelty gate."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> NoveltyGateNode:
        """Extract topic, set initial stage and status, generate run_id."""
        ctx.state.set_stage(Stage.RESEARCH)
        ctx.state.pipeline_status = PipelineStatus.RUNNING
        if not ctx.state.run_id:
            ctx.state.run_id = str(uuid.uuid4())[:8]
        ctx.state.integrity_fix_count = 0
        ctx.state.messages.append(
            {
                "role": "system",
                "content": f"Pipeline started for topic: {ctx.state.topic}",
            }
        )
        # Traceability: optional copilot checkpoint (--copilot flag).
        # No-op when ctx.deps.config.copilot_enabled is False (default).
        from academic_pipeline.traceability.copilot import copilot_checkpoint

        comment = await copilot_checkpoint(
            name="post_intake",
            summary="Intake complete. Topic + research question drafted. About to start research phase.",
            timeout_s=60,
            enabled=ctx.deps.config.copilot_enabled,
        )
        if comment:
            ctx.state.copilot_comments["post_intake"] = comment
        return NoveltyGateNode()


@dataclass
class NoveltyGateNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Pre-flight novelty check (SCI Spec 3 Phase 1, hard-reject only).

    Searches Semantic Scholar for papers similar to the topic. On REDUNDANT,
    aborts the run with End. On PARTIAL/NOVEL (or if disabled), routes to
    ResearchPhaseNode. Phase 2 will add a differentiation paragraph for PARTIAL.
    """

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> ResearchPhaseNode | End[str]:
        """Run novelty gate when enabled; otherwise pass through."""
        if not ctx.deps.config.novelty_gate_enabled:
            return ResearchPhaseNode()

        from academic_pipeline.research.novelty_gate import compute_novelty_gate

        result = await compute_novelty_gate(
            topic=ctx.state.topic,
            tau_warn=ctx.deps.config.novelty_gate_tau_warn,
            tau_block=ctx.deps.config.novelty_gate_tau_block,
            top_n=ctx.deps.config.novelty_gate_top_n,
        )
        ctx.state.novelty_gate_result = result
        ctx.state.messages.append(
            {
                "role": "system",
                "content": f"Novelty gate: {result.note}",
            }
        )
        if result.verdict == "redundant":
            logger.warning("Novelty gate REJECTED topic %r: %s", ctx.state.topic, result.note)
            ctx.state.pipeline_status = PipelineStatus.ABORTED
            return End(f"BLOCKED by novelty gate: {result.note}")
        # PARTIAL or NOVEL: proceed (Phase 2 will inject differentiation for PARTIAL).
        return ResearchPhaseNode()


@dataclass
class ResearchPhaseNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run the research subgraph and merge results into pipeline state."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> ExperimentClassifierNode:
        """Build ResearchState, run research subgraph, merge outputs."""
        research_state = ResearchState(topic=ctx.state.topic)

        graph = build_research_graph()
        final_state: ResearchState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            ResearchQuestionNode(),
            research_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name="research",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        # Merge research outputs back into pipeline state
        ctx.state.rq_brief = final_state.rq_brief
        ctx.state.methodology_blueprint = final_state.methodology_blueprint
        ctx.state.bibliography = final_state.bibliography
        ctx.state.synthesis = final_state.synthesis
        # Chain-of-Ideas KG (Spec 2 Phase 1). Both fields stay None when
        # config.chain_of_ideas_enabled is false, matching the existing
        # default-off behaviour.
        ctx.state.chain = final_state.chain
        ctx.state.thesis = final_state.thesis
        ctx.state.set_stage(Stage.WRITE)
        ctx.state.version_labels["research"] = "research_v1"
        ctx.state.consecutive_continues = ctx.deps.consecutive_continues
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Research phase complete.",
            }
        )
        return ExperimentClassifierNode()


@dataclass
class WritePhaseNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run the writing subgraph and merge results into pipeline state."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> PreIntegrityNode:
        """Build WritingState, run writing subgraph, merge outputs."""
        ctx.deps.consecutive_continues = ctx.state.consecutive_continues
        writing_state = WritingState(
            topic=ctx.state.topic,
            rq_brief=ctx.state.rq_brief,
            bibliography=ctx.state.bibliography,
            synthesis=ctx.state.synthesis,
            # PRD §6.1.T8 — forward chain + thesis from research subgraph
            # so writing has the development chain anchor + thesis claim.
            chain=ctx.state.chain,
            thesis=ctx.state.thesis,
            paper_draft=ctx.state.paper_draft,
            review_report=ctx.state.review_report,
            revision_roadmap=ctx.state.revision_roadmap,
            response_to_reviewers=ctx.state.response_to_reviewers,
            output_format=ctx.state.output_format,
            # Experiment data
            experiment_results=ctx.state.experiment_results,
            experiment_analysis=ctx.state.experiment_analysis,
            experiment_figures=ctx.state.experiment_figures,
            methodology_blueprint=(
                ctx.state.methodology_blueprint.model_dump_json() if ctx.state.methodology_blueprint else ""
            ),
            # Traceability: forward the per-run numerical store so the writer
            # validator (in ParallelSectionDraftNode) can resolve ⟨num:label⟩ tokens
            # and reject bare numbers when traceability_mode != "off".
            numerical_store=ctx.state.numerical_store,
        )

        graph = build_writing_graph()
        final_state: WritingState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            WritingIntakeNode(),
            writing_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name="writing",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        # Merge writing outputs back into pipeline state
        ctx.state.paper_draft = final_state.paper_draft
        ctx.state.paper_config = final_state.paper_config
        ctx.state.paper_outline = final_state.paper_outline
        ctx.state.argument_blueprint = final_state.argument_blueprint
        ctx.state.figure_package = final_state.figure_package
        ctx.state.citation_grounding = final_state.citation_grounding
        ctx.state.style_profile = final_state.style_profile
        ctx.state.score_history = final_state.score_history
        ctx.state.score_trajectory_flags = final_state.score_trajectory_flags
        ctx.state.latex_source = final_state.latex_source
        ctx.state.bib_source = final_state.bib_source
        ctx.state.pdf_bytes = final_state.pdf_bytes
        ctx.state.output_format = final_state.output_format
        ctx.state.set_stage(Stage.PRE_INTEGRITY)
        ctx.state.version_labels["paper_draft"] = "paper_draft_v1"
        ctx.state.consecutive_continues = ctx.deps.consecutive_continues
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Write phase complete.",
            }
        )
        # Traceability: optional copilot checkpoint (--copilot flag).
        # No-op when ctx.deps.config.copilot_enabled is False (default).
        from academic_pipeline.traceability.copilot import copilot_checkpoint

        comment = await copilot_checkpoint(
            name="post_first_draft",
            summary="First draft complete. About to start integrity check + peer review.",
            timeout_s=60,
            enabled=ctx.deps.config.copilot_enabled,
        )
        if comment:
            ctx.state.copilot_comments["post_first_draft"] = comment
        return PreIntegrityNode()


@dataclass
class ExperimentClassifierNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Classify whether the topic needs experiments, route accordingly."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> ExperimentPhaseNode | WritePhaseNode:
        """Classify topic + route to ExperimentPhaseNode or WritePhaseNode."""
        if not ctx.deps.config.experiment_enabled:
            logger.info("Experiments disabled — skipping to write")
            return WritePhaseNode()

        import os

        if ctx.deps.config.force_experiment or os.environ.get("FORCE_EXPERIMENT", "").lower() == "true":
            logger.info("Force-experiment enabled — skipping classifier, routing to experiment phase")
            ctx.state.set_stage(Stage.EXPERIMENT)
            return ExperimentPhaseNode()

        context = build_context(ctx.state, ["topic", "rq_brief", "synthesis"], node_name="ExperimentClassifierNode")
        result = await traced_agent_run(
            _experiment_agents["experiment_classifier"],
            context,
            deps=ctx.deps,
            name="experiment_classifier",
            phase="02-experiment",
        )
        ctx.state.experiment_classification = result.output
        ctx.deps.predictor_type = result.output.predictor_type

        if result.output.needs_experiments:
            logger.info("Classifier: experiments needed — routing to experiment phase")
            ctx.state.set_stage(Stage.EXPERIMENT)
            return ExperimentPhaseNode()

        logger.info("Classifier: no experiments needed — routing to write")
        return WritePhaseNode()


@dataclass
class ExperimentPhaseNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run the experiment subgraph (interactive ML agent + judge loop)."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> WritePhaseNode | AbortNode:
        """Run experiment subgraph; route to WritePhaseNode or AbortNode."""
        rq_text = ctx.state.rq_brief.model_dump_json() if ctx.state.rq_brief else ""
        mb_text = ctx.state.methodology_blueprint.model_dump_json() if ctx.state.methodology_blueprint else ""
        synth_text = ctx.state.synthesis.model_dump_json() if ctx.state.synthesis else ""

        experiment_state = ExperimentState(
            topic=ctx.state.topic,
            run_id=ctx.state.run_id,
            rq_brief=rq_text,
            methodology_blueprint=mb_text,
            synthesis=synth_text,
            predictor_type=ctx.deps.predictor_type,
        )

        graph = build_experiment_graph()
        final_state: ExperimentState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            ExperimentEntryNode(),
            experiment_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name="experiment",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        if final_state.results is not None and final_state.analysis is not None:
            ctx.state.experiment_plan = final_state.plan
            ctx.state.experiment_code = final_state.generated_code
            ctx.state.experiment_results = final_state.results
            ctx.state.experiment_analysis = final_state.analysis
            # ExperimentResults.figures is list[FigureArtifact | str]; the
            # LLM-generated Dagster workspace writes string paths. Convert
            # strings into minimal FigureArtifact instances so the writing
            # phase's VisualizationNode sees a non-empty inventory instead
            # of silently dropping the strings.
            from pathlib import Path as _Path

            raw_figures = final_state.results.figures if final_state.results else []
            converted: list[FigureArtifact] = []
            for f in raw_figures:
                if isinstance(f, FigureArtifact):
                    converted.append(f)
                elif isinstance(f, str):
                    converted.append(
                        FigureArtifact(figure_type="png", filename=str(_Path(f).resolve()), caption="", data_base64="")
                    )
            ctx.state.experiment_figures = converted
            # Traceability: populate numerical store from experiment metrics when enabled.
            # No-op when traceability_mode == "off" so the existing pipeline path is unchanged.
            if ctx.deps.config.traceability_mode in {"partial", "full"}:
                from academic_pipeline.experiment.producers import (
                    extract_numerical_products_from_result,
                )

                products = extract_numerical_products_from_result(
                    result=final_state.results,
                    run_id=ctx.state.run_id or "unknown-run",
                    source_step="experiment.analysis",
                    code=getattr(final_state.results, "code", None) or None,
                    code_filename="analysis.py",
                )
                for p in products:
                    try:
                        ctx.state.numerical_store = ctx.state.numerical_store.add(p)
                    except Exception:
                        # Duplicate label across re-runs — skip silently rather than crash.
                        logger.debug("Skipping duplicate numerical product label: %s", p.label)
            # Traceability: optional copilot checkpoint (--copilot flag).
            # No-op when ctx.deps.config.copilot_enabled is False (default).
            from academic_pipeline.traceability.copilot import copilot_checkpoint

            comment = await copilot_checkpoint(
                name="post_experiment_design",
                summary="Experiment phase complete. Results + analysis available. About to start writing phase.",
                timeout_s=60,
                enabled=ctx.deps.config.copilot_enabled,
            )
            if comment:
                ctx.state.copilot_comments["post_experiment_design"] = comment
            ctx.state.set_stage(Stage.WRITE)
            ctx.state.messages.append({"role": "system", "content": "Experiment phase complete."})
            return WritePhaseNode()

        # No results returned. Distinguish "interrupted mid-run" from "tried hard
        # and gave up" — they look the same to this branch (final_state.results
        # is None either way) but require very different responses.
        #
        # Interrupted runs (SIGTERM, dropped SSE stream, watchdog kill):
        #   error_history is empty because no agent explicitly failed. Going to
        #   AbortNode here would mark pipeline_status=ABORTED, write the
        #   terminal End snapshot, and seal the run as unresumable
        #   (pydantic_graph load_next() returns None on a graph that's reached
        #   End → "Unable to restore snapshot from state persistence" on resume).
        #   Instead we raise so pydantic_graph records the ExperimentPhaseNode
        #   snapshot as 'error'. On resume, _reset_crashed_snapshots() flips
        #   that back to 'created', the node re-runs, and its inner subgraph
        #   resumes from its own snapshots (bundle/scorer/ML iter1 stay intact).
        #
        # Real failures (ml_engineer gave up after retries, dataset URLs all
        #   broken, etc.): error_history is populated and the abort path runs.
        if not final_state.error_history:
            ctx.state.messages.append(
                {
                    "role": "system",
                    "content": (
                        "Experiment phase did not produce results and recorded no "
                        "explicit failures. Treating as interruption (SIGTERM / "
                        "network drop / watchdog kill). Run remains resumable via "
                        "`make resume THREAD_ID=<id>`."
                    ),
                }
            )
            raise RuntimeError(
                f"Experiment phase did not produce results "
                f"(run_id={ctx.state.run_id}, error_history empty). "
                "Likely interrupted by signal or network drop. "
                "Use `make resume` to continue from the last successful subgraph node."
            )

        logger.warning(
            "Experiment phase failed after %d retries — aborting (errors: %s)",
            ctx.state.experiment_fix_count,
            final_state.error_history,
        )
        if ctx.deps.config.experiment_alert_email:
            from academic_pipeline.tools.execution.sanity import send_dataset_alert

            await send_dataset_alert(
                topic=ctx.state.topic,
                missing_datasets=final_state.error_history,
                config=ctx.deps.config,
            )
        ctx.state.messages.append({"role": "system", "content": "Experiment phase failed. Aborting."})
        return AbortNode()


@dataclass
class PreIntegrityNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run pre-review integrity check and route based on verdict."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> ReviewPhaseNode | IntegrityFixNode:
        """Build IntegrityState, run integrity subgraph, route on verdict."""
        ctx.state.inject_reinforcement(Stage.PRE_INTEGRITY)
        integrity_state = IntegrityState(
            paper_draft=ctx.state.paper_draft,
            integrity_phase="pre",
            compliance_stage="2.5",
            citation_grounding=ctx.state.citation_grounding,
        )

        graph = build_integrity_graph()
        fix_n = ctx.state.integrity_fix_count
        final_state: IntegrityState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            IntegrityCheckNode(),
            integrity_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name=f"pre_integrity_{fix_n}",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        # Merge integrity report back
        ctx.state.integrity_report = final_state.integrity_report
        if final_state.compliance_report is not None:
            ctx.state.compliance_reports["2.5"] = final_state.compliance_report.model_dump()
        ctx.state.set_stage(Stage.PRE_INTEGRITY)

        # Route based on verdict
        raw_verdict = str(ctx.state.integrity_report.get("verdict", "FAIL")).upper()
        try:
            verdict = Verdict(raw_verdict)
        except ValueError:
            logger.warning("Unknown verdict '%s', treating as FAIL", raw_verdict)
            verdict = Verdict.FAIL

        if verdict in (Verdict.PASS, Verdict.PASS_WITH_CONDITIONS):
            ctx.state.integrity_fix_count = 0
            logger.info("Pre-integrity PASS — routing to review")
            return ReviewPhaseNode()

        # FAIL — check if we've exceeded max fix loops
        if ctx.state.integrity_fix_count >= ctx.deps.config.max_integrity_fix_loops:
            logger.warning("Pre-integrity FAIL but max fix loops reached — forcing to review")
            return ReviewPhaseNode()

        logger.info("Pre-integrity FAIL — routing to integrity fix")
        return IntegrityFixNode()


@dataclass
class IntegrityFixNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Auto-fix integrity issues and re-check."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> PreIntegrityNode:
        """Increment fix counter, append fix message, route back to integrity."""
        ctx.state.integrity_fix_count += 1
        ctx.state.messages.append(
            {
                "role": "system",
                "content": (
                    f"Integrity fix round {ctx.state.integrity_fix_count}. "
                    f"Issues: {ctx.state.summarize_integrity_issues()}"
                ),
            }
        )
        logger.info(
            "Integrity fix round %d/%d",
            ctx.state.integrity_fix_count,
            ctx.deps.config.max_integrity_fix_loops,
        )
        return PreIntegrityNode()


@dataclass
class ReviewPhaseNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run the review subgraph — read-only, no revision routing."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> FinalIntegrityNode:
        """Build ReviewState, run review subgraph, route to final integrity."""
        ctx.state.inject_reinforcement(Stage.REVIEW)
        ctx.deps.consecutive_continues = ctx.state.consecutive_continues
        review_state = ReviewState(
            paper_draft=ctx.state.paper_draft,
            review_report=ctx.state.review_report,
            revision_roadmap=ctx.state.revision_roadmap,
            response_to_reviewers=ctx.state.response_to_reviewers,
        )

        graph = build_review_graph()
        final_state: ReviewState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            FieldAnalystNode(),
            review_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name="review",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        # Merge review outputs back
        ctx.state.review_report = final_state.review_report
        ctx.state.revision_roadmap = final_state.revision_roadmap
        ctx.state.response_to_reviewers = final_state.response_to_reviewers
        ctx.state.editorial_decision = str(final_state.editorial_decision or "")
        ctx.state.novelty_report = final_state.novelty_report
        ctx.state.persona_reviews = list(final_state.persona_reviews)
        ctx.state.cascade_result = final_state.cascade_result
        ctx.state.set_stage(Stage.FINAL_INTEGRITY)
        ctx.state.messages.append({"role": "system", "content": "Review phase complete."})
        return FinalIntegrityNode()


@dataclass
class FinalIntegrityNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Run final integrity check requiring zero blocking issues."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> FinalizeNode | FinalIntegrityFixNode:
        """Build IntegrityState with final phase, run integrity subgraph."""
        ctx.state.inject_reinforcement(Stage.FINAL_INTEGRITY)
        integrity_state = IntegrityState(
            paper_draft=ctx.state.paper_draft,
            integrity_phase="final",
            compliance_stage="4.5",
            citation_grounding=ctx.state.citation_grounding,
        )

        graph = build_integrity_graph()
        fix_n = ctx.state.integrity_fix_count
        final_state: IntegrityState = await _run_subgraph_with_persistence(  # pyright: ignore[reportAssignmentType]
            graph,
            IntegrityCheckNode(),
            integrity_state,
            ctx.deps,
            run_id=ctx.state.run_id,
            subgraph_name=f"final_integrity_{fix_n}",
            pipeline_state=ctx.state,
            pipeline_ref=getattr(ctx.deps, "_pipeline_ref", None),
        )

        # Merge integrity report back
        ctx.state.integrity_report = final_state.integrity_report
        if final_state.compliance_report is not None:
            ctx.state.compliance_reports["4.5"] = final_state.compliance_report.model_dump()
        ctx.state.set_stage(Stage.FINAL_INTEGRITY)

        # Route based on verdict
        raw_verdict = str(ctx.state.integrity_report.get("verdict", "FAIL")).upper()
        try:
            verdict = Verdict(raw_verdict)
        except ValueError:
            logger.warning("Unknown verdict '%s', treating as FAIL", raw_verdict)
            verdict = Verdict.FAIL

        if verdict in (Verdict.PASS, Verdict.PASS_WITH_CONDITIONS):
            ctx.state.integrity_fix_count = 0
            ctx.state.material_passport = MaterialPassport(
                origin_skill="FinalIntegrityNode",
                verification_status="VERIFIED",
                integrity_pass_date=datetime.now(UTC),
                version_label="v1",
            )
            logger.info("Final integrity PASS — routing to finalize")
            return FinalizeNode()

        # FAIL — check max fix loops
        if ctx.state.integrity_fix_count >= ctx.deps.config.max_integrity_fix_loops:
            logger.warning("Final integrity FAIL but max fix loops reached — forcing to finalize")
            return FinalizeNode()

        logger.info("Final integrity FAIL — routing to final integrity fix")
        return FinalIntegrityFixNode()


@dataclass
class FinalIntegrityFixNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Auto-fix final integrity issues and re-check."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> FinalIntegrityNode:
        """Increment fix counter, route back to final integrity check."""
        ctx.state.integrity_fix_count += 1
        ctx.state.messages.append(
            {
                "role": "system",
                "content": (
                    f"Final integrity fix round {ctx.state.integrity_fix_count}. "
                    f"Issues: {ctx.state.summarize_integrity_issues()}"
                ),
            }
        )
        logger.info(
            "Final integrity fix round %d/%d",
            ctx.state.integrity_fix_count,
            ctx.deps.config.max_integrity_fix_loops,
        )
        return FinalIntegrityNode()


@dataclass
class FinalizeNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Final formatting pass on the paper."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> SummaryNode:
        """Run final formatting and route to summary."""
        ctx.state.set_stage(Stage.FINALIZE)
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Finalization complete. Paper ready for delivery.",
            }
        )
        return SummaryNode()


@dataclass
class SummaryNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Generate pipeline summary and mark as completed."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> End[str]:
        """Set completed status, render summary, return End."""
        ctx.state.set_stage(Stage.SUMMARY)
        ctx.state.stages[Stage.SUMMARY.value] = {"status": "completed"}
        ctx.state.pipeline_status = PipelineStatus.COMPLETED
        summary = (
            f"Pipeline complete for topic: {ctx.state.topic}\n"
            f"Stages completed: {list(ctx.state.stages.keys()) or 'all'}\n"
            f"Integrity fix rounds: {ctx.state.integrity_fix_count}"
        )
        ctx.state.messages.append(
            {
                "role": "system",
                "content": summary,
            }
        )
        return End(summary)


@dataclass
class AbortNode(BaseNode[PipelineState, PipelineDeps, str]):
    """Abort the pipeline after a reject decision."""

    async def run(self, ctx: GraphRunContext[PipelineState, PipelineDeps]) -> End[str]:
        """Set aborted status and return End."""
        ctx.state.pipeline_status = PipelineStatus.ABORTED
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Pipeline aborted.",
            }
        )
        return End("Pipeline aborted.")


ALL_NODES = [
    IntakeNode,
    NoveltyGateNode,
    ResearchPhaseNode,
    ExperimentClassifierNode,
    ExperimentPhaseNode,
    WritePhaseNode,
    PreIntegrityNode,
    IntegrityFixNode,
    ReviewPhaseNode,
    FinalIntegrityNode,
    FinalIntegrityFixNode,
    FinalizeNode,
    SummaryNode,
    AbortNode,
]
