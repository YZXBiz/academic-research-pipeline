"""PydanticAI writing graph nodes.

Twelve node dataclasses forming the writing subgraph: intake routing,
literature strategy, HITL checkpoint, structure architecture, argument
building, draft writing, citation compliance, abstract generation,
visualization, merge, peer review, and final formatting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.core.enums import PHASE_DIRS, Stage
from academic_pipeline.models.writing import (  # runtime: used in node type hints
    PaperConfig,
    Section,
    SectionSpec,
)
from academic_pipeline.runtime.context import build_context, build_curated_context, format_health_prefix
from academic_pipeline.runtime.evaluator import run_with_evaluation
from academic_pipeline.runtime.hard_vetos import (
    no_bare_latex_commands,
    no_placeholder_tokens,
)
from academic_pipeline.runtime.trace_logger import traced_agent_run
from academic_pipeline.runtime.validators import validate_state  # runtime: used in DraftWriterNode
from academic_pipeline.writing.agents import agents as _agents
from academic_pipeline.writing.citation_grounding import (
    GroundingPair,
    build_grounding_pairs,
    parse_citations,
)
from academic_pipeline.writing.context_specs import (
    DRAFT_WRITER_CONTEXT_SPEC,
    SECTION_WRITER_CONTEXT_SPEC,
)
from academic_pipeline.writing.state import WritingState


logger = logging.getLogger(__name__)

# Code-enforced hard vetos for section/paper output. See utils/hard_vetos.py.
# These OVERRIDE LLM PASS verdicts when forbidden patterns appear in output text.
_SECTION_VETOS = [no_placeholder_tokens, no_bare_latex_commands]

# ---------------------------------------------------------------------------
# Evaluation rubrics — one per evaluated node
# ---------------------------------------------------------------------------

_RUBRIC_STRUCTURE = """\
Evaluate this paper structure/outline for academic quality:

- Logical flow (0-10): Do sections follow a coherent narrative arc?
- Section coverage (0-10): Are required sections present (intro, lit review, methods, results, discussion, conclusion)?
- IMRaD compliance (0-10): Does the structure follow the appropriate reporting standard?
- Scope alignment (0-10): Does the outline match the research question scope?

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_ARGUMENT = """\
Evaluate this argument blueprint for academic rigor:

- Argument strength (0-10): Are claims well-supported by evidence?
- Evidence linkage (0-10): Are sources correctly connected to claims?
- Logical coherence (0-10): Does the reasoning flow without gaps or fallacies?
- Counterargument coverage (0-10): Are opposing viewpoints addressed?

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_SECTION_DRAFT = """\
Evaluate this paper section draft for academic quality.

If a TRACEABILITY CONTEXT block is provided ABOVE this rubric, every specific
quantitative claim in the section must be traceable to it (or to a cited
[bibkey] primary source) or marked `[PENDING: ...]`.

Dimensions:

- Depth (0-10): Does the section go beyond surface-level treatment?
- Citations (0-10): Are claims supported by specific cited sources?
- Relevance (0-10): Does the content directly serve the research question?
- Completeness (0-10): Are there gaps in coverage or missing subsections?
- Numerical traceability (0-10): Every specific number, statistic, p-value,
  effect size, sample size, percentage, or test result MUST be either
  (a) traceable verbatim to upstream artifacts in TRACEABILITY CONTEXT,
  (b) cited to a primary source with [bibkey] adjacent, or
  (c) explicitly marked `[PENDING: ...]`.
  Score 0 if ANY specific stat is invented (e.g., "I²=86.3%" with no
  upstream source). Hedge language like "interim", "preliminary", or
  "subject to revision" does NOT excuse invented specifics.
- Placeholder hygiene (0-10): No raw `XXXX`, `[redacted]`, `TODO`, `TBD`,
  `CRD42024-XXXXXX`, `NCT0XXXXXXX`, or `[INSERT...]` patterns. Use
  `[PENDING: ...]` instead. Score 0 if any forbidden pattern present.

Score each dimension. PASS if ALL dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak."""

_RUBRIC_CITATION = """\
Evaluate this citation compliance check for accuracy:

- Format consistency (0-10): Do all citations follow the same style (APA7)?
- Coverage (0-10): Are all claims properly cited?
- Accuracy (0-10): Do in-text citations match the bibliography entries?
- Completeness (0-10): Are there any orphaned references or missing citations?

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_DRAFT = """\
Evaluate this full paper draft for academic quality:

- Coherence (0-10): Does the paper read as a unified narrative?
- Academic tone (0-10): Is the writing style appropriate for a peer-reviewed journal?
- Transitions (0-10): Do sections connect smoothly?
- Completeness (0-10): Are all sections fully developed with no stubs?

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""

_RUBRIC_FORMATTER = """\
Evaluate this formatted paper output:

- Formatting consistency (0-10): Are headings, fonts, spacing uniform throughout?
- Figure/table placement (0-10): Are figures and tables correctly referenced and placed?
- Bibliography format (0-10): Is the reference list properly formatted?
- Overall presentation (0-10): Is the paper submission-ready?

Score each dimension. PASS if all dimensions >= 7.
If NEEDS_IMPROVEMENT, specify exactly which dimensions are weak and what's missing."""


_MAX_TITLE_WORDS = 15
_MAX_TITLE_CHARS = 120


def _trim_overlong_title(title: str) -> str:
    """Truncate paper titles that bust the ACL/IEEE 2-line guideline.

    Cuts at the first colon, em-dash, or period after position
    ``_MAX_TITLE_CHARS``; falls back to a hard slice. Logs a warning
    so the regression appears in events.jsonl when it fires — fixing
    the structure_architect prompt is the durable fix; this guard is
    belt-and-suspenders.
    """
    word_count = len(title.split())
    if word_count <= _MAX_TITLE_WORDS and len(title) <= _MAX_TITLE_CHARS:
        return title

    logger.warning(
        "paper title exceeds limits (%d words, %d chars): %r — truncating",
        word_count,
        len(title),
        title,
    )

    # Prefer cutting at a natural break.
    for sep in (": ", " — ", " – ", ". "):  # noqa: RUF001 — en-dash & em-dash both common in titles
        idx = title.find(sep)
        if 0 < idx < _MAX_TITLE_CHARS:
            head = title[:idx].strip()
            if len(head.split()) <= _MAX_TITLE_WORDS:
                return head

    # Hard slice on word boundary as a last resort.
    words = title.split()[:_MAX_TITLE_WORDS]
    return " ".join(words).rstrip(",;:")


def _build_traceability_context(state: WritingState) -> str:
    """Concat upstream artifacts that the section writer may legitimately reference.

    Used to give the evaluator panel real ammo for the Numerical traceability
    rubric dimension. Any specific number in a section must trace back to one
    of these artifacts (or to a cited primary source).
    """
    parts: list[str] = []
    if state.synthesis is not None:
        parts.append(f"## SYNTHESIS\n{state.synthesis.model_dump_json(indent=2)}")
    if state.experiment_results is not None:
        parts.append(f"## EXPERIMENT_RESULTS\n{state.experiment_results.model_dump_json(indent=2)}")
    if state.experiment_analysis is not None:
        parts.append(f"## EXPERIMENT_ANALYSIS\n{state.experiment_analysis.model_dump_json(indent=2)}")
    return "\n\n".join(parts) if parts else ""


@dataclass
class IntakeNode(BaseNode[WritingState, PipelineDeps, str]):
    """Analyze topic and route to literature strategist or structure architect."""

    async def run(
        self, ctx: GraphRunContext[WritingState, PipelineDeps]
    ) -> LiteratureStrategistNode | StructureArchitectNode:
        """Analyze the topic and route based on bibliography presence."""
        context = build_context(ctx.state, ["topic", "rq_brief", "synthesis"])
        result = await traced_agent_run(
            _agents["intake"], context, deps=ctx.deps, name="intake", phase=PHASE_DIRS[Stage.WRITE]
        )

        # Preserve any CLI-provided authors when the intake agent overwrites paper_config.
        cli_authors = ctx.state.paper_config.authors if ctx.state.paper_config else []
        if isinstance(result.output, PaperConfig):
            ctx.state.paper_config = (
                result.output.model_copy(update={"authors": list(cli_authors)}) if cli_authors else result.output
            )
        else:
            logger.warning(
                "intake agent output type %s — paper_config not updated",
                type(result.output).__name__,
            )

        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})

        if ctx.state.bibliography:
            return LiteratureStrategistNode()

        return StructureArchitectNode()


@dataclass
class LiteratureStrategistNode(BaseNode[WritingState, PipelineDeps, str]):
    """Develop a literature integration strategy from the bibliography."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> StructureArchitectNode:
        """Analyze bibliography and produce a literature integration plan."""
        context = build_context(ctx.state, ["topic", "bibliography", "synthesis"])
        result = await traced_agent_run(
            _agents["literature_strategist"],
            context,
            deps=ctx.deps,
            name="literature_strategist",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.literature_strategy = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return StructureArchitectNode()


@dataclass
class StructureArchitectNode(BaseNode[WritingState, PipelineDeps, str]):
    """Design the paper outline and structural blueprint."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> ArgumentBuilderNode:
        """Generate the paper outline from topic, RQ brief, and synthesis."""
        context = build_context(
            ctx.state,
            ["topic", "rq_brief", "synthesis", "bibliography", "experiment_results", "experiment_analysis"],
        )
        result = await run_with_evaluation(
            agent=_agents["structure_architect"],
            context=context,
            rubric=_RUBRIC_STRUCTURE,
            deps=ctx.deps,
            name="structure_architect",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.paper_outline = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return ArgumentBuilderNode()


@dataclass
class ArgumentBuilderNode(BaseNode[WritingState, PipelineDeps, str]):
    """Build the argument blueprint from the paper outline."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> SectionPlannerNode:
        """Generate argument blueprints for each section of the outline."""
        context = build_context(
            ctx.state,
            ["topic", "paper_outline", "synthesis", "bibliography", "experiment_analysis"],
        )
        result = await run_with_evaluation(
            agent=_agents["argument_builder"],
            context=context,
            rubric=_RUBRIC_ARGUMENT,
            deps=ctx.deps,
            name="argument_builder",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.argument_blueprint = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return SectionPlannerNode()


def _is_parent_section(heading: str, all_headings: list[str]) -> bool:
    """A section is a parent if other sections share its numbered prefix."""
    match = re.match(r"^(?:Section\s+)?(\d+)[\.\:\s](?!\d)", heading)
    if not match:
        return False
    num = match.group(1)
    children = [h for h in all_headings if h != heading and re.match(rf"^(?:Section\s+)?{num}\.\d+", h)]
    return len(children) > 0


@dataclass
class SectionPlannerNode(BaseNode[WritingState, PipelineDeps, str]):
    """Convert outline + argument blueprint into per-section specs."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> ParallelSectionDraftNode:
        """Build per-section specs from outline and argument blueprint."""
        validate_state(ctx.state, ["paper_outline", "argument_blueprint"], "SectionPlannerNode")
        outline = ctx.state.paper_outline
        blueprint = ctx.state.argument_blueprint
        specs: list[SectionSpec] = []
        if outline is not None:
            sections = outline.sections if hasattr(outline, "sections") else []
            all_headings = [s.title for s in sections]
            parent_summaries: dict[str, str] = {}
            for section in sections:
                if _is_parent_section(section.title, all_headings):
                    parent_summaries[section.title] = section.content_summary
            sections = [s for s in sections if not _is_parent_section(s.title, all_headings)]
            for i, section in enumerate(sections):
                # Build adjacent context from neighboring sections
                prev_summary = sections[i - 1].content_summary if i > 0 else ""
                next_summary = sections[i + 1].content_summary if i < len(sections) - 1 else ""
                adjacent = ""
                if prev_summary:
                    adjacent += f"Previous section: {prev_summary}\n"
                if next_summary:
                    adjacent += f"Next section: {next_summary}"

                # Prepend parent context for child sections
                for parent_title, parent_summary in parent_summaries.items():
                    parent_match = re.match(r"^(?:Section\s+)?(\d+)[\.\:\s]", parent_title)
                    if parent_match and section.title.startswith(parent_match.group(1) + "."):
                        adjacent = f"Parent section ({parent_title}): {parent_summary}\n" + adjacent

                # Find matching argument chain from blueprint
                arg_chain = None
                if blueprint is not None and hasattr(blueprint, "sub_arguments"):
                    for chain in blueprint.sub_arguments:
                        if chain.claim and section.title.lower() in chain.claim.lower():
                            arg_chain = chain
                            break

                specs.append(
                    SectionSpec(
                        heading=section.title,
                        level=1,
                        word_count_target=section.word_count_target,
                        purpose=section.purpose,
                        content_guidance=section.content_summary,
                        key_sources=section.key_sources,
                        argument_chain=arg_chain,
                        adjacent_context=adjacent,
                    )
                )
        ctx.state.section_specs = specs
        ctx.state.messages.append(
            {"role": "system", "content": f"Section planner produced {len(specs)} section specs."}
        )
        return ParallelSectionDraftNode()


@dataclass
class ParallelSectionDraftNode(BaseNode[WritingState, PipelineDeps, str]):
    """Draft all sections concurrently via asyncio.gather."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> SectionMergerNode:
        """Draft each section concurrently via asyncio.gather."""

        async def draft_section(spec: SectionSpec) -> Section:
            # Per-agent ContextSpec rollout (PRD §6.10.T3). Curates state
            # to topic + experiment artifacts; the SectionSpec stays a
            # per-call argument since it isn't a state field.
            curated = build_curated_context(ctx.state, SECTION_WRITER_CONTEXT_SPEC)
            context = f"Section spec:\n{spec.model_dump_json(indent=2)}"
            if curated:
                context = f"{curated}\n\n{context}"
            result = await run_with_evaluation(
                agent=_agents["section_writer"],
                context=context,
                rubric=_RUBRIC_SECTION_DRAFT,
                deps=ctx.deps,
                name=f"section_writer_{spec.heading.replace(' ', '_').lower()[:30]}",
                phase=PHASE_DIRS[Stage.WRITE],
                traceability_context=_build_traceability_context(ctx.state),
                hard_vetos=_SECTION_VETOS,
            )

            # Traceability: enforce numerical grounding when the layer is enabled.
            # Inline (not wrapped) because the factory + mode check is 4 lines and
            # the validator needs per-run state (numerical_store) so it can't be
            # attached as a PydanticAI @agent.output_validator at registration time.
            # Section uses .content/.heading; the validator's _HasText Protocol
            # expects .text/.section_name, so a tiny dataclass adapter bridges them.
            if ctx.deps.config.traceability_mode != "off":
                from dataclasses import dataclass as _dc

                from academic_pipeline.traceability.validators import (
                    ABORTING_PHRASES,
                    FORBIDDEN_PHRASES,
                    make_numeric_output_validator,
                )

                @_dc
                class _SectionAdapter:
                    text: str
                    section_name: str

                validator = make_numeric_output_validator(
                    ctx.state.numerical_store,
                    FORBIDDEN_PHRASES,
                    ABORTING_PHRASES,
                )
                # Validator raises ModelRetry / UnexpectedModelBehavior on failure;
                # both propagate up — that's the intended gating behavior.
                validator(_SectionAdapter(text=result.output.content, section_name=result.output.heading))

            return result.output

        tasks = [draft_section(spec) for spec in ctx.state.section_specs]
        if tasks:
            ctx.state.section_drafts = list(await asyncio.gather(*tasks))
        else:
            ctx.state.section_drafts = []
        ctx.state.messages.append(
            {
                "role": "system",
                "content": f"Parallel drafting complete: {len(ctx.state.section_drafts)} sections drafted.",
            }
        )
        return SectionMergerNode()


@dataclass
class SectionMergerNode(BaseNode[WritingState, PipelineDeps, str]):
    """Merge drafted sections into a complete PaperDraft."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> CitationComplianceNode:
        """Combine section drafts into one PaperDraft."""
        from academic_pipeline.models.shared import Reference
        from academic_pipeline.models.writing import (
            PaperDraft,
        )

        sections = ctx.state.section_drafts

        seen_headings: set[str] = set()
        deduped: list[Section] = []
        for section in sections:
            if section.heading not in seen_headings:
                seen_headings.add(section.heading)
                deduped.append(section)
            else:
                logger.warning("Dropped duplicate section: %s", section.heading)
        sections = deduped

        outline = ctx.state.paper_outline

        title = outline.title if outline is not None else ctx.state.topic
        # Runtime guard against the "4-line title" failure mode that the
        # structure_architect prompt also forbids. ACL/IEEE/most venues
        # cap titles at ~15 words / 2 typeset lines. Anything longer
        # signals an agent that didn't follow the title-constraints
        # block in structure_architect.yaml; truncate at the first
        # natural break (colon or period) and warn loudly so the
        # regression is visible in events.jsonl.
        title = _trim_overlong_title(title)
        total_words = sum(s.word_count for s in sections)

        # Abstract is generated by the dedicated abstract agent (run later in
        # ParallelAbstractVizNode). Setting it here from sections[0][:500]
        # truncates mid-token (e.g. "**Objectives." -> "**Ob") and the real
        # abstract was never written back to the draft anyway. Use empty
        # string as a placeholder; MergePhase5Node will populate it from
        # state.abstract_result["abstract_text"] via model_copy.
        abstract = ""

        references: list[Reference] = []
        if ctx.state.bibliography is not None:
            references = [
                Reference(id=s.id, full_citation=s.citation, doi=s.doi) for s in ctx.state.bibliography.sources
            ]

        pc = ctx.state.paper_config
        # Only carry authors when real ones were supplied (CLI --author or
        # copilot interview). Empty list is fine: paper_renderer handles a
        # missing author block by omitting it, and acl.sty/IEEEtran both
        # render a no-author title cleanly. Fabricating "Anonymous /
        # Independent Researcher" puts a fake byline on the PDF first page.
        authors = list(pc.authors) if pc is not None and pc.authors else []

        draft = PaperDraft(
            title=title,
            abstract=abstract,
            authors=authors,
            keywords=["research", "study", "analysis"],
            sections=sections,
            references=references,
            total_word_count=total_words,
        )
        ctx.state.paper_draft = draft
        ctx.state.messages.append(
            {
                "role": "system",
                "content": f"Section merger complete: {len(sections)} sections, {total_words} words.",
            }
        )
        return CitationComplianceNode()


@dataclass
class DraftWriterNode(BaseNode[WritingState, PipelineDeps, str]):
    """Write the full paper draft from outline and argument blueprint."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> CitationComplianceNode:
        """Generate the paper draft from structural and argument inputs."""
        validate_state(ctx.state, ["paper_outline", "argument_blueprint"], "DraftWriterNode")
        # Per-agent ContextSpec rollout (PRD §6.10.T2). Spec instance lives in
        # writing/context_specs.py; build_curated_context performs strict
        # isinstance(spec, ContextSpec) per AP75 + filters numerical_store.
        context = build_curated_context(ctx.state, DRAFT_WRITER_CONTEXT_SPEC)
        result = await run_with_evaluation(
            agent=_agents["draft_writer"],
            context=context,
            rubric=_RUBRIC_DRAFT,
            deps=ctx.deps,
            name="draft_writer",
            phase=PHASE_DIRS[Stage.WRITE],
            hard_vetos=_SECTION_VETOS,
        )
        ctx.state.paper_draft = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return CitationComplianceNode()


@dataclass
class CitationComplianceNode(BaseNode[WritingState, PipelineDeps, str]):
    """Audit and fix citations in the draft using citation tools."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> ParallelAbstractVizNode:
        """Run citation compliance checks on the paper draft."""
        context = build_context(ctx.state, ["paper_draft", "bibliography"])
        result = await run_with_evaluation(
            agent=_agents["citation_compliance"],
            context=context,
            rubric=_RUBRIC_CITATION,
            deps=ctx.deps,
            name="citation_compliance",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.citation_audit = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})
        return ParallelAbstractVizNode()


@dataclass
class ParallelAbstractVizNode(BaseNode[WritingState, PipelineDeps, str]):
    """Run abstract generation and visualization in parallel."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> MergePhase5Node:
        """Execute abstract and visualization agents concurrently via asyncio.gather."""

        async def _run_abstract() -> None:
            context = build_context(ctx.state, ["paper_draft", "rq_brief", "topic"])
            result = await traced_agent_run(
                _agents["abstract"], context, deps=ctx.deps, name="abstract", phase=PHASE_DIRS[Stage.WRITE]
            )
            ctx.state.abstract_result = result.output.model_dump()
            ctx.state.messages.append({"role": "assistant", "content": result.output.abstract_text})

        async def _run_visualization() -> None:
            # Build the available_figures inventory from the PNGs the
            # experiment-phase Dagster workspace produced. The curator
            # agent picks from this inventory instead of generating
            # matplotlib code (the writing-phase sandbox runner was
            # retired by the figures-via-dagster pivot).
            figures = list(ctx.state.experiment_figures or [])
            inventory_lines: list[str] = []
            for i, f in enumerate(figures, 1):
                hint = (
                    f.caption or ""
                )  # caption is str (default ""); explicit `or ""` keeps prompt clean if it ever becomes None
                inventory_lines.append(f"{i}. path={f.filename}  hint={hint!r}")
            inventory_block = (
                "\n".join(inventory_lines) if inventory_lines else "(none — experiment phase produced no figures)"
            )

            base_context = build_context(ctx.state, ["paper_draft", "paper_outline"])
            context = f"available_figures:\n{inventory_block}\n\n{base_context}"
            result = await traced_agent_run(
                _agents["visualization"],
                context,
                deps=ctx.deps,
                name="visualization",
                phase=PHASE_DIRS[Stage.WRITE],
            )
            ctx.state.figure_package = result.output
            ctx.state.messages.append({"role": "assistant", "content": result.output.model_dump_json(indent=2)})

        await asyncio.gather(_run_abstract(), _run_visualization())
        return MergePhase5Node()


@dataclass
class MergePhase5Node(BaseNode[WritingState, PipelineDeps, str]):
    """Merge abstract, visualization, and draft into the review-ready paper."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> CitationGroundingNode:
        """Merge all writing artifacts before peer review."""
        # Extract abstract text
        abstract_text = ""
        if isinstance(ctx.state.abstract_result, dict):
            abstract_text = ctx.state.abstract_result.get(
                "abstract_text",
                json.dumps(ctx.state.abstract_result, indent=2, default=str),
            )
        else:
            abstract_text = str(ctx.state.abstract_result)

        # Persist the real abstract back into the draft so the renderer uses
        # the full text instead of the empty placeholder set by SectionMergerNode.
        # Only write back when the agent produced a real `abstract_text` field;
        # the JSON-dump fallback above is a debug string, not a real abstract,
        # and must not clobber an existing draft abstract.
        # PaperDraft is frozen — must use model_copy.
        from academic_pipeline.models.writing import PaperDraft as _PaperDraft

        _real_abstract = (
            ctx.state.abstract_result.get("abstract_text") if isinstance(ctx.state.abstract_result, dict) else None
        )
        _existing_draft = ctx.state.paper_draft
        if isinstance(_existing_draft, _PaperDraft) and _real_abstract:
            ctx.state.paper_draft = _existing_draft.model_copy(update={"abstract": _real_abstract})

        # Extract draft text from the typed PaperDraft.
        draft = ctx.state.paper_draft
        if draft is not None:
            section_texts = [s.content for s in draft.sections]
            draft_text = "\n\n".join(section_texts) if section_texts else draft.abstract
            if not draft_text:
                draft_text = draft.model_dump_json(indent=2)
        else:
            draft_text = ""

        # Extract figure package
        fig = ctx.state.figure_package
        figure_text = fig.model_dump_json(indent=2) if fig is not None else ""

        merged = f"Abstract:\n{abstract_text}\n\nDraft:\n{draft_text}\n\nFigures:\n{figure_text}"
        ctx.state.internal_review = merged
        ctx.state.messages.append(
            {
                "role": "system",
                "content": "Phase 5 merge complete. Draft ready for peer review.",
            }
        )
        return CitationGroundingNode()


def _reconstruct_paper_markdown(draft: Any) -> str:
    """Rebuild section-headed Markdown from a PaperDraft.

    The citation parser needs `# Heading` lines to track which section each
    `[@sNNN]` appears under; PaperDraft stores heading and content separately.
    """
    parts: list[str] = []
    for section in draft.sections:
        hashes = "#" * max(1, min(section.level, 6))
        parts.append(f"{hashes} {section.heading}\n\n{section.content}")
    return "\n\n".join(parts)


def _format_grounding_pairs(pairs: list[GroundingPair]) -> str:
    """Render grounding pairs as the citation_grounding agent's input block."""
    blocks: list[str] = []
    for i, pair in enumerate(pairs, 1):
        blocks.append(
            f"--- Pair {i} ---\n"
            f"citation_id: {pair.citation_id}\n"
            f"section: {pair.section}\n"
            f"claim_text: {pair.claim_text}\n"
            f"source_title: {pair.source_title}\n"
            f"source_year: {pair.source_year}\n"
            f"source_annotation: {pair.source_annotation}"
        )
    return "\n\n".join(blocks)


@dataclass
class CitationGroundingNode(BaseNode[WritingState, PipelineDeps, str]):
    """Semantically verify every in-text citation against its source annotation.

    Closes the dominant failure class from run-0511-2107: section writers
    attaching citations to claims the cited source does not substantiate
    (e.g. TAM cited to Sculley's ML technical-debt paper instead of Davis
    1989). Parses `[@sNNN]` occurrences out of the merged draft, joins each
    with its bibliography annotation, and asks the citation_grounding agent
    to classify the match. The report flows downstream to the integrity
    phase.
    """

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> FigureVerificationNode:
        """Run citation grounding; skip cleanly when there's nothing to ground."""
        draft = ctx.state.paper_draft
        bibliography = ctx.state.bibliography
        if draft is None or bibliography is None:
            logger.info("Citation grounding skipped: missing paper_draft or bibliography.")
            return FigureVerificationNode()

        paper_md = _reconstruct_paper_markdown(draft)
        citations = parse_citations(paper_md)
        pairs = build_grounding_pairs(bibliography, citations)
        if not pairs:
            logger.info("Citation grounding skipped: no groundable citations in draft.")
            return FigureVerificationNode()

        context = (
            f"Verify the following {len(pairs)} citation usage(s). For each pair, "
            f"classify whether the source annotation supports the claim.\n\n"
            f"{_format_grounding_pairs(pairs)}"
        )
        result = await traced_agent_run(
            _agents["citation_grounding"],
            context,
            deps=ctx.deps,
            name="citation_grounding",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.citation_grounding = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.summary})
        return FigureVerificationNode()


@dataclass
class FigureVerificationNode(BaseNode[WritingState, PipelineDeps, str]):
    """Verify figures with VLM (GPT-5.2)."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> PeerReviewerNode:
        """Check figure quality using vision model."""
        if not ctx.state.figure_package or not ctx.state.figure_package.figures:
            logger.info("No figures to verify. Skipping to peer review.")
            return PeerReviewerNode()
        context = build_context(ctx.state, ["figure_package"], node_name="FigureVerificationNode")
        result = await traced_agent_run(
            _agents["figure_verifier"], context, deps=ctx.deps, name="figure_verifier", phase=PHASE_DIRS[Stage.WRITE]
        )
        ctx.state.figure_verification = result.output
        ctx.state.messages.append({"role": "assistant", "content": result.output.summary})
        return PeerReviewerNode()


@dataclass
class PeerReviewerNode(BaseNode[WritingState, PipelineDeps, str]):
    """Peer review the draft. Per-node evaluation replaces the revision loop."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> FormatterNode:
        """Review the draft and store the review report."""
        context = format_health_prefix(ctx.state.messages) + build_context(
            ctx.state, ["paper_draft", "internal_review", "citation_audit", "abstract_result"]
        )
        result = await traced_agent_run(
            _agents["peer_reviewer"], context, deps=ctx.deps, name="peer_reviewer", phase=PHASE_DIRS[Stage.WRITE]
        )
        report_text = result.output.report or result.output.summary
        ctx.state.internal_review = report_text
        ctx.state.messages.append({"role": "assistant", "content": report_text})
        return FormatterNode()


@dataclass
class FormatterNode(BaseNode[WritingState, PipelineDeps, str]):
    """Apply final formatting and produce the deliverable paper."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> BibTexGeneratorNode | End[str]:
        """Format the final paper. Route to LaTeX pipeline if output_format is latex."""
        # Editorial-gate hard-fail (PRD §6.10.T4) — surface ALL unresolved
        # ⟨num:label⟩ tokens at once so authors get one comprehensive fix
        # list instead of substituting one-at-a-time at LaTeX compile.
        if ctx.state.paper_draft is not None and ctx.state.numerical_store.products:
            from academic_pipeline.traceability.errors import SubstitutionFailure
            from academic_pipeline.traceability.substitution import find_unresolved_tokens

            full_text = "\n\n".join(s.content for s in ctx.state.paper_draft.sections)
            unresolved = find_unresolved_tokens(full_text, ctx.state.numerical_store)
            if unresolved:
                raise SubstitutionFailure(
                    f"TRC003: editorial gate rejects paper_draft — {len(unresolved)} unresolved "
                    f"⟨num:label⟩ token(s): {unresolved}",
                    label=unresolved[0],
                    section_name=None,
                    store_label_count=len(ctx.state.numerical_store.products),
                )
        context = build_context(ctx.state, ["paper_draft", "style_profile"])
        result = await run_with_evaluation(
            agent=_agents["formatter"],
            context=context,
            rubric=_RUBRIC_FORMATTER,
            deps=ctx.deps,
            name="formatter",
            phase=PHASE_DIRS[Stage.WRITE],
        )
        ctx.state.formatted_output = result.output.model_dump()
        ctx.state.messages.append({"role": "assistant", "content": result.output.formatted_content})

        if ctx.state.output_format == "latex":
            return BibTexGeneratorNode()
        from academic_pipeline.runtime.paper_renderer import render_markdown

        if ctx.state.paper_draft is not None:
            from academic_pipeline.models.writing import PaperDraft as PaperDraftModel

            if isinstance(ctx.state.paper_draft, PaperDraftModel):
                return End(render_markdown(ctx.state.paper_draft))
        return End(result.output.formatted_content)


@dataclass
class BibTexGeneratorNode(BaseNode[WritingState, PipelineDeps, str]):
    """Generate .bib file from verified bibliography metadata."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> LatexCompilerNode:
        """Convert bibliography entries to BibTeX format."""
        from academic_pipeline.tools.bibliography.bibtex import generate_bibtex_file

        bib_data = ctx.state.bibliography
        entries: list[dict[str, Any]] = [s.model_dump() for s in bib_data.sources] if bib_data is not None else []

        ctx.state.bib_source = generate_bibtex_file(entries)
        logger.info("Generated %d BibTeX entries", len(entries))
        ctx.state.messages.append({"role": "system", "content": f"BibTeX generation complete: {len(entries)} entries."})
        return LatexCompilerNode()


def _build_experiment_runs_for_appendix(state: WritingState) -> list:
    """Reconstruct run-shaped objects for the Code appendix from the populated store.

    Walks state.numerical_store, groups source_code_line entries by source_run_id,
    computes producing_lines from the line numbers, and returns a list of
    structural objects matching the _CodeRun Protocol in
    traceability/code_appendix.py.

    Returns empty list if state has no experiment_results (e.g., topic that
    doesn't need experiments) — the Code appendix is only emitted when there's
    something to show.
    """
    from dataclasses import dataclass

    if not state.experiment_results or not getattr(state.experiment_results, "code", None):
        return []

    by_run: dict[str, set[int]] = {}
    for product in state.numerical_store.products.values():
        if product.source_code_line is None:
            continue
        try:
            lineno = int(product.source_code_line.rsplit(":", 1)[-1])
        except (ValueError, IndexError):
            continue
        by_run.setdefault(product.source_run_id, set()).add(lineno)

    @dataclass(frozen=True)
    class _Run:
        run_id: str
        code: str
        code_filename: str
        producing_lines: tuple[int, ...]

    runs: list[_Run] = []
    if by_run:
        for run_id, lines in by_run.items():
            runs.append(
                _Run(
                    run_id=run_id,
                    code=state.experiment_results.code,
                    code_filename=getattr(state.experiment_results, "code_filename", "analysis.py"),
                    producing_lines=tuple(sorted(lines)),
                )
            )
    else:
        # No traced lines but we have code — emit a single run with empty
        # producing_lines so the code still renders (without anchors). This
        # keeps reviewers oriented even when AST tracing failed.
        runs.append(
            _Run(
                run_id="experiment",
                code=state.experiment_results.code,
                code_filename=getattr(state.experiment_results, "code_filename", "analysis.py"),
                producing_lines=(),
            )
        )
    return runs


@dataclass
class LatexCompilerNode(BaseNode[WritingState, PipelineDeps, str]):
    """Compile LaTeX source + BibTeX to PDF via tectonic."""

    async def run(self, ctx: GraphRunContext[WritingState, PipelineDeps]) -> End[str]:
        """Render PaperDraft to IEEE PDF via pandoc, keep .tex as artifact.

        Figure execution lives here (not in a separate node) because pandoc
        runs in a per-call tempdir and the markdown emits relative paths
        like ``figures/figure_NN.png`` — those PNGs must be produced in
        the same tempdir or pandoc cannot find them.
        """
        import tempfile

        from academic_pipeline.runtime.authors_yaml import (
            load_authors_yaml,
            resolve_authors_yaml_path,
        )
        from academic_pipeline.runtime.paper_renderer import render_latex, render_markdown
        from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing
        from academic_pipeline.tools.rendering.latex_compiler import compile_pdf_pandoc

        # §6.7.T3 — authors.yaml gate. Resolution order: cwd (project root)
        # only for now; run-dir overrides land alongside §6.7.T3's broader
        # plan. Refusing to compile a no-authors paper here saves a 1-2 hour
        # run from emitting an "Author, Affiliation TBD" placeholder.
        authors_path = resolve_authors_yaml_path(Path.cwd())
        if authors_path is None:
            raise AuthorsYamlMissing(searched_paths=[str(Path.cwd() / "authors.yaml")])
        # Validate the file shape — an existing-but-broken file is not a pass.
        load_authors_yaml(authors_path)

        bib_source = ctx.state.bib_source

        from academic_pipeline.models.writing import PaperDraft as PaperDraftModel

        if isinstance(ctx.state.paper_draft, PaperDraftModel):
            markdown = render_markdown(
                ctx.state.paper_draft,
                figure_package=ctx.state.figure_package,
            )
            tex_source = render_latex(ctx.state.paper_draft, bib_source)
        else:
            markdown = ctx.state.formatted_output.get("formatted_content", "")
            tex_source = markdown

        ctx.state.latex_source = tex_source

        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir)

            # Copy pre-rendered PNGs from the experiment workspace into the
            # pandoc build dir under figures/. The relative paths in the
            # rendered LaTeX (figures/<basename>.png) resolve against pandoc's
            # cwd at compile time. The previous sandbox-runner approach failed
            # 5/5 in production because the agent's matplotlib scripts couldn't
            # reach the experiment data — the figures-via-dagster pivot retired
            # the sandbox runner.
            if ctx.state.figure_package is not None:
                figures_subdir = build_dir / "figures"
                figures_subdir.mkdir(parents=True, exist_ok=True)
                copied = 0
                for spec in ctx.state.figure_package.figures:
                    if spec.source_path and spec.source_path.exists():
                        shutil.copy(spec.source_path, figures_subdir / spec.source_path.name)
                        copied += 1
                logger.info(
                    "copied %d/%d figures into pandoc build_dir",
                    copied,
                    len(ctx.state.figure_package.figures),
                )

            pdf_path = await compile_pdf_pandoc(
                markdown,
                bib_source,
                build_dir,
                numerical_store=ctx.state.numerical_store,
                traceability_mode=ctx.deps.config.traceability_mode,
                experiment_runs=_build_experiment_runs_for_appendix(ctx.state),
            )

            if pdf_path and pdf_path.exists():
                ctx.state.pdf_bytes = pdf_path.read_bytes()
                logger.info("PDF compiled via pandoc (%d bytes)", len(ctx.state.pdf_bytes))
                ctx.state.messages.append(
                    {"role": "system", "content": "PDF compiled via pandoc. LaTeX source also available."}
                )
            else:
                logger.warning("pandoc PDF compilation failed")
                ctx.state.messages.append(
                    {"role": "system", "content": "PDF compilation failed. .tex and .bib still available."}
                )

        return End(tex_source)


def build_writing_graph() -> Graph:
    """Build the writing subgraph with all 17 nodes."""
    return Graph(  # pyright: ignore[reportReturnType]
        name="writing",
        nodes=[
            IntakeNode,
            LiteratureStrategistNode,
            StructureArchitectNode,
            ArgumentBuilderNode,
            SectionPlannerNode,
            ParallelSectionDraftNode,
            SectionMergerNode,
            DraftWriterNode,
            CitationComplianceNode,
            ParallelAbstractVizNode,
            MergePhase5Node,
            CitationGroundingNode,
            FigureVerificationNode,
            PeerReviewerNode,
            FormatterNode,
            BibTexGeneratorNode,
            LatexCompilerNode,
        ],
    )
