"""PydanticAI review graph nodes.

Five node dataclasses forming the review subgraph: field analysis,
parallel reviewer dispatch, point-wise novelty review (gated by config),
editorial synthesis with coaching routing, and revision coaching.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic_ai.tool_manager import ToolManager
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import (
    PHASE_DIRS,
    EditorialDecision,  # runtime: used in node body
    Stage,
)
from academic_pipeline.models.cascade import CascadeStageName, StageResult, StageVerdict
from academic_pipeline.models.novelty_gate import NeighborPaper
from academic_pipeline.models.novelty_report import (
    ClaimAssessment,
    ClaimVerdict,
    ContributionClaim,
)
from academic_pipeline.models.persona_review import (
    PersonaReviewOutput,  # noqa: TC001 — used at runtime in return-type annotation
)
from academic_pipeline.review.agents import PERSONA_REVIEWER_AGENTS, REVIEWER_AGENTS
from academic_pipeline.review.agents import agents as _agents
from academic_pipeline.review.cascade_aggregation import aggregate_cascade_result
from academic_pipeline.review.cascade_stages import (
    run_methodology_stage,
    run_narrative_stage,
    run_novelty_stage,
    run_numerical_grounding_stage,
)
from academic_pipeline.review.context_specs import (
    EDITORIAL_SYNTHESIZER_CONTEXT_SPEC,
    PERSONA_REVIEWER_SPECS,
)
from academic_pipeline.review.novelty_aggregation import aggregate_novelty_report
from academic_pipeline.review.state import ReviewState
from academic_pipeline.runtime.context import build_context, build_curated_context
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.runtime.validators import validate_state  # runtime: used in EditorialSynthesizerNode


logger = logging.getLogger(__name__)


@dataclass
class FieldAnalystNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Analyze the paper's field and configure the reviewer team."""

    async def run(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> ParallelReviewerNode:
        """Run field analysis on the paper draft and set up reviewer config."""
        context = build_context(ctx.state, ["paper_draft"])
        result = await traced_agent_run(
            _agents["field_analyst"], context, deps=ctx.deps, name="field_analyst", phase=PHASE_DIRS[Stage.REVIEW]
        )
        ctx.state.review_report["field_analysis"] = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": result.output.review_strategy})
        return ParallelReviewerNode()


@dataclass
class ParallelReviewerNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Dispatch all peer reviewers concurrently.

    When ``config.persona_reviewers_enabled`` is false (default), dispatches the
    legacy 3-reviewer panel (methodology, domain, perspective) and stores
    PeerReviewReport dicts on ``state.reviewer_reports``.

    When ``config.persona_reviewers_enabled`` is true, dispatches the 3
    persona-anchored reviewers (senior_gatekeeper, applied_practitioner,
    methodology_purist) and stores ``PersonaReviewOutput`` instances on
    ``state.persona_reviews``. The legacy ``reviewer_reports`` is left empty.
    """

    async def run(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> PointWiseNoveltyReviewerNode:
        """Run all reviewers in parallel via asyncio.gather."""
        if ctx.deps.config.persona_reviewers_enabled:
            await self._run_persona_panel(ctx)
        else:
            await self._run_legacy_panel(ctx)
        return PointWiseNoveltyReviewerNode()

    async def _run_legacy_panel(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> None:
        """Dispatch the legacy 3 reviewers and store PeerReviewReport dicts."""
        tasks = [self._run_reviewer(ctx, reviewer_id, agent_key) for reviewer_id, agent_key in REVIEWER_AGENTS]
        results = await asyncio.gather(*tasks)
        for reviewer_id, agent_key, report in results:
            ctx.state.reviewer_reports.append(
                {
                    "reviewer_id": reviewer_id,
                    "agent": agent_key,
                    "report": report,
                }
            )

    async def _run_persona_panel(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> None:
        """Dispatch the 3 persona-anchored reviewers and store PersonaReviewOutput."""
        tasks = [
            self._run_persona_reviewer(ctx, reviewer_id, agent_key)
            for reviewer_id, agent_key in PERSONA_REVIEWER_AGENTS
        ]
        results = await asyncio.gather(*tasks)
        for _reviewer_id, _agent_key, persona_review in results:
            ctx.state.persona_reviews.append(persona_review)

    async def _run_reviewer(
        self,
        ctx: GraphRunContext[ReviewState, PipelineDeps],
        reviewer_id: str,
        agent_key: str,
    ) -> tuple[str, str, dict[str, Any]]:
        """Run a single legacy reviewer agent and return its report."""
        context = build_context(ctx.state, ["paper_draft"])
        with ToolManager.parallel_execution_mode("sequential"):
            result = await traced_agent_run(
                _agents[agent_key], context, deps=ctx.deps, name=agent_key, phase=PHASE_DIRS[Stage.REVIEW]
            )
        ctx.state.messages.append(
            {
                "role": "assistant",
                "content": f"[{reviewer_id}] {result.output.summary_assessment}",
            }
        )
        return reviewer_id, agent_key, result.output.model_dump()

    async def _run_persona_reviewer(
        self,
        ctx: GraphRunContext[ReviewState, PipelineDeps],
        reviewer_id: str,
        agent_key: str,
    ) -> tuple[str, str, PersonaReviewOutput]:
        """Run a single persona-anchored reviewer agent and return its structured output."""
        # Per-agent ContextSpec rollout (PRD §6.10.T3). PERSONA_REVIEWER_SPECS
        # has one ContextSpec per persona — picks the right one per agent_key.
        context = build_curated_context(ctx.state, PERSONA_REVIEWER_SPECS[agent_key])
        with ToolManager.parallel_execution_mode("sequential"):
            result = await traced_agent_run(
                _agents[agent_key], context, deps=ctx.deps, name=agent_key, phase=PHASE_DIRS[Stage.REVIEW]
            )
        persona_review: PersonaReviewOutput = result.output
        ctx.state.messages.append(
            {
                "role": "assistant",
                "content": f"[{reviewer_id}] {persona_review.one_paragraph_summary}",
            }
        )
        return reviewer_id, agent_key, persona_review


def _render_manuscript(state: ReviewState) -> str:
    """Render the paper draft into a single text string for claim extraction."""
    draft = state.paper_draft
    if draft is None:
        return ""
    # Support PaperDraft (BaseModel) and plain dicts (used in some tests).
    if isinstance(draft, dict):
        title = str(draft.get("title", ""))
        abstract = str(draft.get("abstract", ""))
        content = str(draft.get("content", ""))
        sections_repr = ""
        sections = draft.get("sections")
        if isinstance(sections, list):
            parts: list[str] = []
            for s in sections:
                if isinstance(s, dict):
                    parts.append(f"## {s.get('title', '')}\n{s.get('content', '')}")
                else:
                    parts.append(str(s))
            sections_repr = "\n\n".join(parts)
        body = "\n\n".join(p for p in (title, abstract, content, sections_repr) if p)
        return body
    # PaperDraft model.
    title = getattr(draft, "title", "") or ""
    abstract = getattr(draft, "abstract", "") or ""
    sections = getattr(draft, "sections", None) or []
    section_chunks: list[str] = []
    for s in sections:
        s_title = getattr(s, "title", "") or (s.get("title", "") if isinstance(s, dict) else "")
        s_content = getattr(s, "content", "") or (s.get("content", "") if isinstance(s, dict) else "")
        section_chunks.append(f"## {s_title}\n{s_content}")
    return "\n\n".join(p for p in (f"# {title}", abstract, *section_chunks) if p)


def _build_assessor_prompt(claim: ContributionClaim, neighbors: list[NeighborPaper]) -> str:
    """Format one claim + retrieved neighbors as the prompt for the assessor."""
    lines = [
        "Assess the novelty of the following contribution claim against the retrieved prior works.",
        "",
        "CLAIM:",
        f"  claim_id: {claim.claim_id}",
        f"  dimension: {claim.dimension.value}",
        f"  section: {claim.section}",
        f"  cited_traces: {', '.join(claim.cited_traces) if claim.cited_traces else '(none)'}",
        f"  text: {claim.claim_text}",
        "",
        f"NEAREST PRIOR WORKS ({len(neighbors)}):",
    ]
    if not neighbors:
        lines.append("  (no candidates returned by Semantic Scholar)")
    else:
        for i, n in enumerate(neighbors, start=1):
            lines.append(
                f"  [{i}] title={n.title!r} similarity={n.similarity:.3f} "
                f"doi={n.doi or '(none)'} s2_id={n.semantic_scholar_id or '(none)'}"
            )
            if n.abstract_excerpt:
                lines.append(f"      abstract: {n.abstract_excerpt}")
    return "\n".join(lines)


@dataclass
class PointWiseNoveltyReviewerNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Per-claim novelty assessment via Semantic Scholar retrieval (SCI Spec 4 Phase 1).

    Catches the citation-fabrication pattern: writer cites a prior work to
    anchor a claim, but the prior work doesn't actually support the claim.
    Per-claim retrieval is structurally immune to hedge-language tricks
    because the claim either matches a prior work or doesn't.

    Skipped entirely when ``config.pointwise_novelty_enabled`` is false (default).
    """

    async def run(
        self, ctx: GraphRunContext[ReviewState, PipelineDeps]
    ) -> CascadedReviewNode | EditorialSynthesizerNode:
        """Extract claims, retrieve prior works per claim, aggregate to NoveltyReport."""
        if not ctx.deps.config.pointwise_novelty_enabled:
            return _next_after_pointwise(ctx)

        from academic_pipeline.tools.bibliography.semantic_scholar import search_s2_by_title

        manuscript = _render_manuscript(ctx.state)
        if not manuscript.strip():
            logger.warning("PointWiseNoveltyReviewerNode: empty manuscript, skipping")
            return _next_after_pointwise(ctx)

        # 1. Extract claims
        try:
            claims_result = await traced_agent_run(
                _agents["claim_extractor"],
                manuscript,
                deps=ctx.deps,
                name="claim_extractor",
                phase=PHASE_DIRS[Stage.REVIEW],
            )
            claims: list[ContributionClaim] = list(claims_result.output.claims)
        except Exception as e:  # broad: skip novelty review on extractor failure (PNV002)
            logger.warning("PointWiseNoveltyReviewerNode: claim extraction failed: %s", e)
            return _next_after_pointwise(ctx)

        # 2. For each claim, retrieve neighbors + assess
        top_n = ctx.deps.config.pointwise_novelty_top_n_per_claim
        assessments: list[ClaimAssessment] = []
        for claim in claims:
            try:
                raw = await search_s2_by_title(claim.claim_text)
                parsed = _json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(parsed, dict) or parsed.get("degraded"):
                    candidates = []
                else:
                    matches = parsed.get("matches") or []
                    candidates = matches[:top_n] if isinstance(matches, list) else []
                neighbors: list[NeighborPaper] = []
                for c in candidates:
                    if not isinstance(c, dict):
                        continue
                    sim_raw = c.get("similarity")
                    try:
                        sim = float(sim_raw) if sim_raw is not None else 0.0
                    except (TypeError, ValueError):
                        sim = 0.0
                    sim = max(0.0, min(1.0, sim))
                    doi_val = c.get("doi") or None
                    s2_id_val = c.get("paperId")
                    neighbors.append(
                        NeighborPaper(
                            title=str(c.get("title") or ""),
                            doi=doi_val or None,
                            semantic_scholar_id=str(s2_id_val) if s2_id_val else None,
                            similarity=sim,
                            abstract_excerpt=str(c.get("abstract") or "")[:200],
                        )
                    )
            except Exception as e:  # PNV003 — skip this claim
                logger.warning(
                    "PointWiseNoveltyReviewerNode: retrieval failed for claim %s: %s",
                    claim.claim_id,
                    e,
                )
                neighbors = []

            try:
                assessor_prompt = _build_assessor_prompt(claim, neighbors)
                assessment_result = await traced_agent_run(
                    _agents["claim_novelty_assessor"],
                    assessor_prompt,
                    deps=ctx.deps,
                    name=f"claim_novelty_assessor_{claim.claim_id}",
                    phase=PHASE_DIRS[Stage.REVIEW],
                )
                assessments.append(assessment_result.output)
            except Exception as e:
                logger.warning(
                    "PointWiseNoveltyReviewerNode: assessment failed for claim %s: %s",
                    claim.claim_id,
                    e,
                )
                # Default to NOVEL when the assessor fails so we don't block falsely.
                assessments.append(
                    ClaimAssessment(
                        claim_id=claim.claim_id,
                        verdict=ClaimVerdict.NOVEL,
                        nearest_prior_works=neighbors,
                        differentiation_note=f"Assessor failed: {e}",
                    )
                )

        # 3. Aggregate
        report = aggregate_novelty_report(claims, assessments)
        ctx.state.novelty_report = report
        if report.overall_verdict == "REJECT_NOVELTY":
            ctx.state.messages.append(
                {
                    "role": "system",
                    "content": (f"Point-wise novelty review: REJECT_NOVELTY (blockers: {report.rejection_blockers})"),
                }
            )
            logger.warning(
                "Point-wise novelty review verdict REJECT_NOVELTY; blockers=%s",
                report.rejection_blockers,
            )
        return _next_after_pointwise(ctx)


def _next_after_pointwise(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
) -> CascadedReviewNode | EditorialSynthesizerNode:
    """Pick the next node after PointWiseNoveltyReviewerNode.

    When ``cascaded_review_enabled`` is true, route through the cascade
    orchestrator; otherwise preserve the legacy direct route to editorial.
    """
    if getattr(ctx.deps.config, "cascaded_review_enabled", False):
        return CascadedReviewNode()
    return EditorialSynthesizerNode()


@dataclass
class CascadedReviewNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Orchestrate the 4-stage cascaded reviewer pipeline (SCI Spec 6 Phase 1).

    Stages run sequentially:
      A. Numerical grounding (Spec 1 + numerical_claims_auditor agent)
      B. Novelty (Spec 4's NoveltyReport on state)
      C. Methodology (Spec 5's persona findings on state)
      D. Narrative quality (terminal — never short-circuits in Phase 1)

    A SHORT_CIRCUIT_REJECT in any stage halts the cascade; aggregation pads
    later stages as SKIPPED. Phase 1 only populates ``state.cascade_result`` —
    EditorialSynthesizerNode reads it but does not yet enforce the verdict.
    """

    async def run(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> EditorialSynthesizerNode:
        """Run all four stages, short-circuiting on rejection, then route to editorial."""
        manuscript = _render_manuscript(ctx.state)
        stages: list[StageResult] = []

        # Stage A — numerical grounding
        stage_a = await self._safe_run_stage(
            CascadeStageName.NUMERICAL_GROUNDING,
            run_numerical_grounding_stage(ctx, manuscript),
        )
        stages.append(stage_a)
        if stage_a.verdict == StageVerdict.SHORT_CIRCUIT_REJECT:
            ctx.state.cascade_result = aggregate_cascade_result(stages)
            self._log_rejection(ctx, stage_a)
            return EditorialSynthesizerNode()

        # Stage B — novelty
        stage_b = await self._safe_run_stage(
            CascadeStageName.NOVELTY,
            run_novelty_stage(ctx),
        )
        stages.append(stage_b)
        if stage_b.verdict == StageVerdict.SHORT_CIRCUIT_REJECT:
            ctx.state.cascade_result = aggregate_cascade_result(stages)
            self._log_rejection(ctx, stage_b)
            return EditorialSynthesizerNode()

        # Stage C — methodology
        stage_c = await self._safe_run_stage(
            CascadeStageName.METHODOLOGY,
            run_methodology_stage(ctx),
        )
        stages.append(stage_c)
        if stage_c.verdict == StageVerdict.SHORT_CIRCUIT_REJECT:
            ctx.state.cascade_result = aggregate_cascade_result(stages)
            self._log_rejection(ctx, stage_c)
            return EditorialSynthesizerNode()

        # Stage D — narrative (terminal)
        stage_d = await self._safe_run_stage(
            CascadeStageName.NARRATIVE,
            run_narrative_stage(ctx, manuscript),
        )
        stages.append(stage_d)

        ctx.state.cascade_result = aggregate_cascade_result(stages)
        ctx.state.messages.append(
            {
                "role": "system",
                "content": (f"Cascaded review complete: verdict={ctx.state.cascade_result.final_verdict}"),
            }
        )
        return EditorialSynthesizerNode()

    async def _safe_run_stage(self, stage_name: CascadeStageName, coro: Any) -> StageResult:
        """Run a stage coroutine with infrastructure-failure resilience (CSC002).

        On exception, marks the stage as NOT_RUN (rather than short-circuit
        rejecting on infra failure) so the cascade keeps moving.
        """
        try:
            return await coro
        except Exception as e:  # — logged, not blocking
            logger.warning(
                "CascadedReviewNode: stage %s failed (%s); marking NOT_RUN",
                stage_name.value,
                e,
            )
            return StageResult(
                stage=stage_name,
                verdict=StageVerdict.NOT_RUN,
                gate_reason=f"Stage {stage_name.value} crashed: {e}",
            )

    def _log_rejection(
        self,
        ctx: GraphRunContext[ReviewState, PipelineDeps],
        stage: StageResult,
    ) -> None:
        """Log + append a system message announcing the cascade rejection."""
        logger.warning(
            "CascadedReviewNode: short-circuit reject at stage %s — %s",
            stage.stage.value,
            stage.gate_reason,
        )
        ctx.state.messages.append(
            {
                "role": "system",
                "content": (f"Cascaded review SHORT-CIRCUIT REJECT at stage {stage.stage.value}: {stage.gate_reason}"),
            }
        )


@dataclass
class EditorialSynthesizerNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Synthesize all reviewer reports and issue an editorial decision."""

    async def run(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> RevisionCoachingNode | End[str]:
        """Synthesize reviews, parse editorial decision, route accordingly.

        When ``cascaded_review_enabled`` is true, ``state.cascade_result`` is
        included in the context so the editorial synthesizer is aware of the
        cascade outcome. Phase 1: editorial reads but does not yet enforce
        the cascade verdict (Phase 2 will hard-force REJECT on cascade reject).
        """
        validate_state(ctx.state, ["review_report"], "EditorialSynthesizerNode")
        # Per-agent ContextSpec rollout (PRD §6.10.T3). Spec already lists
        # cascade_result so the cascade-aware path stays curated; missing
        # state fields are simply skipped by extract_field_text.
        context = build_curated_context(ctx.state, EDITORIAL_SYNTHESIZER_CONTEXT_SPEC)
        result = await traced_agent_run(
            _agents["editorial_synthesizer"],
            context,
            deps=ctx.deps,
            name="editorial_synthesizer",
            phase=PHASE_DIRS[Stage.REVIEW],
        )

        report_text = result.output.report or result.output.summary
        ctx.state.review_report["synthesis"] = report_text
        ctx.state.messages.append({"role": "assistant", "content": report_text})

        # Map structured decision to EditorialDecision enum
        decision = EditorialDecision.from_label(result.output.decision)
        ctx.state.editorial_decision = decision
        logger.info("Editorial decision: %s", decision)

        # Route: COACHING for Major/Minor Revision, End for Accept/Reject
        if decision in (EditorialDecision.MAJOR_REVISION, EditorialDecision.MINOR_REVISION):
            ctx.state.needs_coaching = True
            return RevisionCoachingNode()

        ctx.state.needs_coaching = False
        return End(f"Review complete. Editorial decision: {decision}")


@dataclass
class RevisionCoachingNode(BaseNode[ReviewState, PipelineDeps, str]):
    """Generate a revision roadmap and response-to-reviewers template."""

    async def run(self, ctx: GraphRunContext[ReviewState, PipelineDeps]) -> End[str]:
        """Build revision guidance from reviewer reports and editorial decision."""
        context = build_context(
            ctx.state,
            ["paper_draft", "reviewer_reports", "review_report"],
        )
        result = await traced_agent_run(
            _agents["eic"], context, deps=ctx.deps, name="eic", phase=PHASE_DIRS[Stage.REVIEW]
        )

        ctx.state.revision_roadmap = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": result.output.summary_assessment})
        return End(f"Review complete with coaching. Decision: {ctx.state.editorial_decision}")


def build_review_graph() -> Graph:
    """Build the review subgraph with all 6 node types."""
    return Graph(  # pyright: ignore[reportReturnType]
        name="review",
        nodes=[
            FieldAnalystNode,
            ParallelReviewerNode,
            PointWiseNoveltyReviewerNode,
            CascadedReviewNode,
            EditorialSynthesizerNode,
            RevisionCoachingNode,
        ],
    )
