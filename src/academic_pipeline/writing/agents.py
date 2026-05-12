"""Writing agent registry.

All Agent.from_file() definitions for the writing subgraph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicCompaction

from academic_pipeline.config import DEFAULT_CONFIG
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.review import (
    FigureVerificationReport,
    PeerReviewOutput,
)
from academic_pipeline.models.writing import (
    AbstractOutput,
    ArgumentBlueprint,
    CitationAudit,
    FigurePackage,
    FormattedPaper,
    LiteratureStrategy,
    PaperConfig,
    PaperDraft,
    PaperOutline,
    Section,
)
from academic_pipeline.runtime.throttle import throttle_hooks
from academic_pipeline.tools.bibliography.citations import (
    convert_citation_style,
    format_citation,
    validate_citation,
)


_COMPACTION = AnthropicCompaction(token_threshold=DEFAULT_CONFIG.compaction_token_threshold)


_AGENTS_DIR = Path(__file__).parent / "specs"

agents: dict[str, Agent[PipelineDeps, Any]] = {
    "intake": Agent.from_file(
        _AGENTS_DIR / "intake.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PaperConfig),
        capabilities=[throttle_hooks],
    ),
    "literature_strategist": Agent.from_file(
        _AGENTS_DIR / "literature_strategist.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(LiteratureStrategy),
        capabilities=[throttle_hooks],
    ),
    "structure_architect": Agent.from_file(
        _AGENTS_DIR / "structure_architect.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PaperOutline),
        capabilities=[throttle_hooks],
    ),
    "argument_builder": Agent.from_file(
        _AGENTS_DIR / "argument_builder.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ArgumentBlueprint),
        capabilities=[throttle_hooks],
    ),
    "draft_writer": Agent.from_file(
        _AGENTS_DIR / "draft_writer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PaperDraft),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "citation_compliance": Agent.from_file(
        _AGENTS_DIR / "citation_compliance.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(CitationAudit),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[format_citation, validate_citation, convert_citation_style],
    ),
    "abstract": Agent.from_file(
        _AGENTS_DIR / "abstract.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(AbstractOutput),
        capabilities=[throttle_hooks],
    ),
    "peer_reviewer": Agent.from_file(
        _AGENTS_DIR / "peer_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(PeerReviewOutput),
        capabilities=[throttle_hooks],
    ),
    "formatter": Agent.from_file(
        _AGENTS_DIR / "formatter.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(FormattedPaper),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "visualization": Agent.from_file(
        _AGENTS_DIR / "visualization.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(FigurePackage),
        capabilities=[throttle_hooks],
    ),
    "revision_coach": Agent.from_file(
        _AGENTS_DIR / "revision_coach.yaml",
        deps_type=PipelineDeps,
        capabilities=[throttle_hooks],
    ),
    "section_writer": Agent.from_file(
        _AGENTS_DIR / "section_writer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(Section),
        capabilities=[throttle_hooks],
    ),
    "figure_verifier": Agent.from_file(
        _AGENTS_DIR / "figure_verifier.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(FigureVerificationReport),
        capabilities=[throttle_hooks],
    ),
}


def validate_formatter_title(output: FormattedPaper) -> FormattedPaper:
    """§6.7.T4 — reject manuscripts whose title exceeds 12 words.

    Pulls the title from ``output.metadata["title"]``; absent / empty title
    is treated as a pass (the formatter sometimes leaves the title to the
    rendering layer). On failure raises ``ModelRetry`` carrying the REN003
    error code so PydanticAI re-prompts the model exactly once
    (``output_retries=1`` configured on the formatter spec).
    """
    title = (output.metadata or {}).get("title", "").strip()
    if not title:
        return output
    word_count = len(title.split())
    if word_count > 12:
        raise ModelRetry(
            f"REN003 title exceeds 12-word limit (got {word_count} words). "
            f"Title: {title!r}. Aim for a 7-10 word declarative title without "
            f"colon-clause stacks."
        )
    return output


# Wire the validator at module load so consumers (graph nodes, tests)
# pick it up without per-call setup. PydanticAI's ``output_validator``
# decorator returns a wrapper; we discard the return because the side
# effect (registration on agents["formatter"]._output_validators) is the
# point.
agents["formatter"].output_validator(validate_formatter_title)
