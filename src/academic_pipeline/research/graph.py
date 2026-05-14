"""PydanticAI research graph nodes.

Eleven node dataclasses forming the research subgraph: question formulation,
methodology design, bibliography search, source verification, knowledge graph,
synthesis, report compilation, cross-model verification, editorial review,
ethics review, and merge. Per-node evaluation replaces DA checkpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.tool_manager import ToolManager
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import (
    PHASE_DIRS,
    EditorialDecision,
    Stage,
)
from academic_pipeline.models.research import IndependentVerificationReport
from academic_pipeline.research.agents import agents as _agents
from academic_pipeline.research.state import ResearchState
from academic_pipeline.runtime.context import build_context
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.runtime.validators import validate_state


if TYPE_CHECKING:
    from academic_pipeline.models.research import Bibliography
    from academic_pipeline.models.review import EditorReview
    from academic_pipeline.models.shared import Source


logger = logging.getLogger(__name__)


def rebuild_bibliography_with_verification(
    bib: Bibliography,
    verification_results: dict[str, bool],
) -> Bibliography:
    """Rebuild a frozen Bibliography with corrected verified flags.

    Sources present in *verification_results* receive the corresponding
    boolean.  Sources absent from the dict are reset to ``None`` (unknown)
    so downstream consumers know they were never explicitly checked.
    """
    updated_sources = []
    for source in bib.sources:
        if source.id in verification_results:
            verified = verification_results[source.id]
            updated_sources.append(source.model_copy(update={"verified": verified, "retraction_check": verified}))
        else:
            updated_sources.append(source.model_copy(update={"verified": None, "retraction_check": None}))
    return bib.model_copy(update={"sources": updated_sources})


_RUBRIC_RQ = """\
Evaluate this research question brief for a systematic academic review:

- Originality (0-10): Does the RQ address a genuine gap in the literature?
- Specificity (0-10): Is the RQ precise enough to guide a focused review?
- Feasibility (0-10): Can the RQ be answered with available literature and methods?
- Testability (0-10): Does it include a clear, falsifiable hypothesis?

A score of 10 means genuinely world-class. Most good outputs score 7-8.

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_ARCHITECT = """\
Evaluate this methodology blueprint for academic rigor:

- Rigor (0-10): Is the chosen paradigm and method appropriate for the RQ?
- Completeness (0-10): Does it cover data strategy, analytical framework, validity?
- Feasibility (0-10): Can this methodology be executed with available resources?
- Reporting (0-10): Is a recognized reporting standard specified (STROBE, PRISMA, etc.)?

A score of 10 means genuinely world-class. Most good outputs score 7-8.

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_BIBLIOGRAPHY = """\
Evaluate this bibliography for a systematic academic review:

- Coverage (0-10): Are there 20+ sources spanning the topic adequately?
- Recency (0-10): Do 50%+ sources come from the last 3 years?
- Relevance (0-10): Do sources directly address the research question?
- Methodological diversity (0-10): Mix of empirical, theoretical, review?
- Source quality (0-10): Peer-reviewed journals, reputable conferences?
- Foundational coverage (0-10): Are meta-analyses and systematic reviews retained? \
Score 0 if a meta-analysis from the first draft was dropped in revision.

A score of 10 means genuinely world-class. Most good outputs score 7-8.

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_SYNTHESIS = """\
Evaluate this literature synthesis for academic quality:

- Coherence (0-10): Does the narrative flow logically from themes to conclusions?
- Evidence (0-10): Are claims supported by specific cited sources?
- Depth (0-10): Does the analysis go beyond summarizing individual papers?
- Balance (0-10): Are conflicting viewpoints represented fairly?
- Gap identification (0-10): Does it clearly identify research gaps?
- Thesis advancement (0-10): Does the synthesis advance the development chain's \
terminal unsolved problem (the thesis)? Themes, debates, and methodology \
recommendations should each contribute to the thesis claim, not drift into \
flat literature review. Score 10 only when every section visibly anchors on \
the thesis; score 0 when the thesis is absent or unrelated.

A score of 10 means genuinely world-class. Most good outputs score 7-8.

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_REPORT = """\
Evaluate this compiled research report:

- Completeness (0-10): Does it include all required sections (RQ, methodology, bibliography, synthesis, gaps)?
- Coherence (0-10): Do sections flow logically? Is the narrative consistent?
- Evidence quality (0-10): Are claims supported by cited sources? Any unsupported assertions?
- Gap identification (0-10): Are research gaps specific and actionable?
- Writing quality (0-10): Is the prose journal-quality? Free of LLM patterns?

Score each dimension. PASS if all dimensions >= 7.
A score of 10 means genuinely world-class. Most good outputs score 7-8."""


@dataclass
class ResearchQuestionNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Transform the topic into a precise research question brief."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> ResearchArchitectNode:
        """Generate the research question brief from the topic."""
        context = build_context(ctx.state, ["topic"], node_name="ResearchQuestionNode")
        result = await traced_agent_run(
            _agents["research_question"],
            context,
            deps=ctx.deps,
            name="research_question",
            phase=PHASE_DIRS[Stage.RESEARCH],
        )
        ctx.state.rq_brief = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json()})
        return ResearchArchitectNode()


@dataclass
class ResearchArchitectNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Design the methodology blueprint from the research question brief."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> BibliographyNode:
        """Generate the methodology blueprint from the RQ brief."""
        context = build_context(ctx.state, ["topic", "rq_brief"], node_name="ResearchArchitectNode")
        result = await traced_agent_run(
            _agents["research_architect"],
            context,
            deps=ctx.deps,
            name="research_architect",
            phase=PHASE_DIRS[Stage.RESEARCH],
        )
        ctx.state.methodology_blueprint = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return BibliographyNode()


@dataclass
class BibliographyNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Search academic databases to build the bibliography."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> SourceVerificationNode:
        """Search academic databases and populate the bibliography."""
        pre_sources = list(ctx.state.bibliography.sources) if ctx.state.bibliography else []

        context = build_context(ctx.state, ["topic", "rq_brief", "methodology_blueprint"], node_name="BibliographyNode")
        with ToolManager.parallel_execution_mode("sequential"):
            result = await traced_agent_run(
                _agents["bibliography"], context, deps=ctx.deps, name="bibliography", phase=PHASE_DIRS[Stage.RESEARCH]
            )
        ctx.state.bibliography = result.output

        if pre_sources and ctx.state.bibliography:
            dropped = check_foundational_sources_retained(pre_sources, list(ctx.state.bibliography.sources))
            if dropped:
                logger.warning(
                    "Foundational sources dropped during revision: %s",
                    [f"{s.id} ({s.title[:50]})" for s in dropped],
                )
                all_sources = list(ctx.state.bibliography.sources) + dropped
                ctx.state.bibliography = ctx.state.bibliography.model_copy(update={"sources": all_sources})
                logger.info("Re-added %d dropped foundational sources", len(dropped))

        ctx.state.messages.append({"role": "assistant", "content": str(result.output)})
        return SourceVerificationNode()


@dataclass
class SourceVerificationNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Verify DOIs and check for retractions in the bibliography."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> ChainOfIdeasNode:
        """Verify DOIs and retraction status for bibliography entries.

        PRD §6.1.T7 Phase 4 routing: routes directly to ChainOfIdeasNode.
        The legacy `KnowledgeGraphNode` was deleted; `legacy_knowledge_graph`
        config flag is retained as a deprecated no-op for back-compat.
        """
        context = build_context(ctx.state, ["bibliography"])
        result = await traced_agent_run(
            _agents["source_verification"],
            context,
            deps=ctx.deps,
            name="source_verification",
            phase=PHASE_DIRS[Stage.RESEARCH],
        )
        ctx.state.review_report["source_verification"] = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": str(result.output)})

        # --- Override pre-labeled verified flags with actual results ---
        report = result.output
        flagged_ids = {fs.source_id for fs in report.flagged_sources if fs.severity in ("High", "Critical")}
        verification_results: dict[str, bool] = {}
        for grade in report.source_quality_matrix:
            verification_results[grade.source_id] = grade.source_id not in flagged_ids
        for fid in flagged_ids:
            verification_results.setdefault(fid, False)

        if ctx.state.bibliography is not None:
            ctx.state.bibliography = rebuild_bibliography_with_verification(
                ctx.state.bibliography, verification_results
            )
            logger.info(
                "Bibliography verified flags overridden: %d sources updated",
                len(verification_results),
            )

        return ChainOfIdeasNode()


@dataclass
class SynthesisNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Synthesize findings from the verified bibliography."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> ReportCompilerNode:
        """Synthesize findings into a narrative from verified sources.

        PRD §6.1.T3 Phase 4: thesis (from ChainOfIdeasNode upstream) is now a
        REQUIRED input — synthesis fails fast if thesis is missing under
        chain_of_ideas_enabled. Includes chain + thesis in agent context so the
        synthesis is anchored on the development chain's terminal unsolved problem.
        """
        # Under default config (chain_of_ideas_enabled=true), thesis must be
        # present from upstream ChainOfIdeasNode. Under legacy flag-off the
        # node skips, so we keep the bibliography-only requirement as fallback.
        if ctx.deps.config.chain_of_ideas_enabled:
            validate_state(ctx.state, ["bibliography", "thesis", "chain"], "SynthesisNode")
            fields = ["rq_brief", "bibliography", "methodology_blueprint", "chain", "thesis"]
        else:
            validate_state(ctx.state, ["bibliography"], "SynthesisNode")
            fields = ["rq_brief", "bibliography", "methodology_blueprint"]
        context = build_context(ctx.state, fields, node_name="SynthesisNode")
        result = await traced_agent_run(
            _agents["synthesis"], context, deps=ctx.deps, name="synthesis", phase=PHASE_DIRS[Stage.RESEARCH]
        )
        ctx.state.synthesis = result.output
        ctx.state.messages.append({"role": "assistant", "content": str(result.output)})
        return ReportCompilerNode()


@dataclass
class ChainOfIdeasNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Extract Chain of Ideas + ThesisStatement from the verified bibliography.

    PRD §6.1.T3 Phase 4 topology: runs BEFORE SynthesisNode under the default
    config so that thesis is available as a required input to synthesis. The
    development chain anchors the synthesis on the field's terminal unsolved
    problem rather than letting synthesis drift into flat literature review.

    When `chain_of_ideas_enabled=false` this node is a no-op pass-through that
    routes directly to SynthesisNode (which then falls back to its
    bibliography-only validate_state branch).
    """

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> SynthesisNode:
        """Extract DevelopmentChain + ThesisStatement; route to SynthesisNode."""
        if not ctx.deps.config.chain_of_ideas_enabled:
            return SynthesisNode()

        validate_state(ctx.state, ["bibliography"], "ChainOfIdeasNode")
        chain_context = build_context(ctx.state, ["bibliography"], node_name="ChainOfIdeasNode")
        chain_result = await traced_agent_run(
            _agents["chain_of_ideas_extractor"],
            chain_context,
            deps=ctx.deps,
            name="chain_of_ideas_extractor",
            phase=PHASE_DIRS[Stage.RESEARCH],
        )
        ctx.state.chain = chain_result.output
        ctx.state.messages.append({"role": "assistant", "content": chain_result.output.model_dump_json(indent=2)})

        last_advance = chain_result.output.milestones[-1].one_sentence_advance if chain_result.output.milestones else ""
        thesis_context = (
            f"Terminal unsolved problem: {chain_result.output.terminal_unsolved_problem}\n"
            f"Last milestone: {last_advance}\n"
            f"Available milestone IDs: "
            f"{', '.join(m.milestone_id for m in chain_result.output.milestones)}"
        )
        thesis_result = await traced_agent_run(
            _agents["thesis_extractor"],
            thesis_context,
            deps=ctx.deps,
            name="thesis_extractor",
            phase=PHASE_DIRS[Stage.RESEARCH],
        )
        ctx.state.thesis = thesis_result.output
        ctx.state.messages.append({"role": "assistant", "content": thesis_result.output.model_dump_json(indent=2)})
        return SynthesisNode()


@dataclass
class ReportCompilerNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Compile the final research report from synthesis and bibliography."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> CrossModelVerificationNode:
        """Compile the full research report from all accumulated state."""
        context = build_context(
            ctx.state,
            ["rq_brief", "synthesis", "bibliography", "methodology_blueprint"],
            node_name="ReportCompilerNode",
        )
        result = await traced_agent_run(
            _agents["report_compiler"], context, deps=ctx.deps, name="report_compiler", phase=PHASE_DIRS[Stage.RESEARCH]
        )
        ctx.state.review_report = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": str(result.output)})
        return CrossModelVerificationNode()


@dataclass
class CrossModelVerificationNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Independent verification of claims using GPT-5.2."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> EditorInChiefNode:
        """Verify research claims with a different model family."""
        context = build_context(
            ctx.state, ["rq_brief", "bibliography", "synthesis"], node_name="CrossModelVerificationNode"
        )
        try:
            result = await traced_agent_run(
                _agents["independent_verifier"],
                context,
                deps=ctx.deps,
                name="independent_verifier",
                phase=PHASE_DIRS[Stage.RESEARCH],
            )
            ctx.state.independent_verification_report = result.output
            ctx.state.messages.append({"role": "assistant", "content": result.output.overall_assessment})
        except (AgentRunError, httpx.HTTPError):
            logger.warning("Independent verification failed — skipping verification", exc_info=True)
            ctx.state.independent_verification_report = IndependentVerificationReport(
                overall_assessment=(
                    "Independent verification skipped due to API error. "
                    "Pipeline proceeding without independent verification."
                ),
                red_flags=["Verification skipped — results not independently verified"],
            )
            ctx.state.messages.append(
                {"role": "system", "content": "Independent verification skipped (API unavailable)."}
            )
        return EditorInChiefNode()


@dataclass
class EditorInChiefNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Q1 journal-level editorial review of the compiled report."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> MergeReviewsNode:
        """Score the report on five dimensions and set needs_revision flag.

        PRD §6.1.T6 routing: returns MergeReviewsNode directly (was:
        EthicsReviewNode pre-T6). The 12-item PRISMA-trAIce ethics checklist
        runs in the integrity subgraph (`EthicsChecklistNode` per §6.5.T1).
        """
        context = build_context(ctx.state, ["review_report"])
        result = await traced_agent_run(
            _agents["editor_in_chief"], context, deps=ctx.deps, name="editor_in_chief", phase=PHASE_DIRS[Stage.RESEARCH]
        )
        review: EditorReview = result.output
        ctx.state.eic_review_structured = review
        ctx.state.needs_revision = review.verdict in (
            EditorialDecision.MAJOR_REVISION,
            EditorialDecision.MINOR_REVISION,
            EditorialDecision.REJECT,
        )
        ctx.state.eic_review = review.summary
        ctx.state.messages.append({"role": "assistant", "content": review.summary})
        return MergeReviewsNode()


@dataclass
class MergeReviewsNode(BaseNode[ResearchState, PipelineDeps, str]):
    """Merge editorial and ethics reviews — terminal decision only."""

    async def run(self, ctx: GraphRunContext[ResearchState, PipelineDeps]) -> End[str]:
        """End the research subgraph. No backward routing.

        PRD §6.1.T6: ethics_verdict gate removed — research-side ethics review
        is gone; the integrity subgraph's `EthicsChecklistNode` (§6.5.T1) is
        the canonical ethics path now and runs after writing.
        """
        eic = ctx.state.eic_review_structured
        if eic is not None:
            logger.info(
                "EIC verdict: %s | needs_revision=%s | summary=%s",
                eic.verdict,
                ctx.state.needs_revision,
                eic.summary[:100] if eic.summary else "N/A",
            )

        final_output = ctx.state.review_report.get("content", "") or str(ctx.state.synthesis) or "Research complete."
        ctx.state.messages.append({"role": "system", "content": "Research subgraph complete."})
        return End(str(final_output))


def check_foundational_sources_retained(
    original_sources: list[Source],
    revised_sources: list[Source],
) -> list[Source]:
    """Check if foundational sources (evidence_tier <= 2) were dropped during revision."""
    revised_ids = {s.id for s in revised_sources}
    return [s for s in original_sources if s.evidence_tier <= 2 and s.id not in revised_ids]


def build_research_graph() -> Graph:
    """Build the research subgraph (PRD §6.1.T6: EthicsReviewNode removed)."""
    return Graph(  # pyright: ignore[reportReturnType]
        name="research",
        nodes=[
            ResearchQuestionNode,
            ResearchArchitectNode,
            BibliographyNode,
            SourceVerificationNode,
            SynthesisNode,
            ChainOfIdeasNode,
            ReportCompilerNode,
            CrossModelVerificationNode,
            EditorInChiefNode,
            MergeReviewsNode,
        ],
    )
