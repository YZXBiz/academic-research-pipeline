"""Writing-phase domain models."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from academic_pipeline.models.shared import (
    ArgumentStrength,
    Author,
    CitationFormat,
    ModifierStyle,
    Reference,
    StructureType,
)

__all__ = [
    "Section",
    "PaperDraft",
    "PaperConfig",
    "LiteratureStrategy",
    "OutlineSection",
    "PaperOutline",
    "SectionSpec",
    "CERChain",
    "ArgumentBlueprint",
    "CitationCorrection",
    "CitationAudit",
    "AbstractOutput",
    "Figure",
    "Table",
    "FigurePackage",
    "FormattedPaper",
    "SentenceLength",
    "ParagraphLength",
    "VocabularyPreferences",
    "CitationStyleMetrics",
    "RegisterShift",
    "StyleProfile",
]


class Section(BaseModel):
    """Paper section with content, word count, and argument strength."""

    model_config = ConfigDict(frozen=True)

    heading: str
    level: int = Field(ge=1, le=4)
    content: str
    word_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    argument_strength: ArgumentStrength | None = None


class PaperDraft(BaseModel):
    """Complete academic paper draft with sections, references, and metadata."""

    model_config = ConfigDict(frozen=True)

    title: str
    abstract: str
    authors: list[Author]
    keywords: list[str] = Field(min_length=3, max_length=6)
    sections: list[Section]
    references: list[Reference]
    total_word_count: int = Field(ge=0)
    citation_format: CitationFormat = "APA7"
    structure_type: StructureType = "IMRaD"


class PaperConfig(BaseModel):
    """Paper configuration from the intake agent."""

    model_config = ConfigDict(frozen=True)

    topic: str = Field(description="Research topic")
    research_question: str = Field(description="Primary research question")
    paper_type: str = Field(
        description="IMRaD / Literature Review / Theoretical / Case Study / Policy Brief / Conference"
    )
    discipline: str = Field(description="Academic discipline")
    target_journal: str = Field(description="Target journal name")
    citation_format: str = Field(description="APA7 / Chicago / MLA / IEEE / Vancouver")
    word_count_target: int = Field(ge=0, description="Target word count")
    body_language: str = Field(default="English", description="Language for paper body")
    existing_materials: str = Field(default="", description="Summary of existing materials provided")
    style_profile: str | None = Field(default=None, description="Style calibration profile if applicable")
    writing_task: str = Field(
        description="full-paper / outline-only / revision / abstract-only / lit-review"
    )
    authors: list[Author] = Field(
        default_factory=list,
        description="Paper authors (from CLI --author flag or intake agent).",
    )


class LiteratureStrategy(BaseModel):
    """Literature integration strategy from the literature strategist agent."""

    model_config = ConfigDict(frozen=True)

    key_themes: list[str] = Field(default_factory=list, description="Major thematic threads identified")
    integration_approach: str = Field(description="How literature integrates into the paper")
    gap_analysis: str = Field(description="Identified gaps in the literature")
    source_categories: dict[str, list[str]] = Field(
        default_factory=dict, description="Sources grouped by category"
    )
    synthesis_notes: str = Field(default="", description="Notes on synthesizing sources")


class OutlineSection(BaseModel):
    """A section in the paper outline."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(description="Section heading")
    word_count_target: int = Field(ge=0, description="Target words for this section")
    purpose: str = Field(description="Purpose of this section")
    content_summary: str = Field(description="What this section should cover")
    key_sources: list[str] = Field(default_factory=list, description="Source IDs assigned")
    transition_to_next: str = Field(default="", description="How to connect to next section")


class PaperOutline(BaseModel):
    """Paper outline from the structure architect agent."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(description="Working title")
    structure_type: str = Field(description="IMRaD / Thematic / Chronological / etc.")
    sections: list[OutlineSection] = Field(
        default_factory=list, description="Ordered list of section definitions"
    )
    total_word_count_target: int = Field(ge=0, description="Total target word count")
    evidence_map: str = Field(default="", description="Source-to-section assignment")
    estimated_word_counts: dict[str, int] = Field(
        default_factory=dict, description="Word count targets per section"
    )
    notes: str = Field(default="", description="Architectural notes")


class CERChain(BaseModel):
    """Claim-Evidence-Reasoning chain."""

    model_config = ConfigDict(frozen=True)

    claim: str = Field(description="The claim being made")
    evidence: list[str] = Field(default_factory=list, description="Evidence with source IDs")
    reasoning: str = Field(description="Reasoning connecting evidence to claim")
    counter_argument: str = Field(default="", description="Potential counter-argument")
    rebuttal: str = Field(default="", description="Rebuttal to counter-argument")
    strength: str = Field(
        default="adequate", description="Compelling / Strong / Adequate / Weak"
    )


class SectionSpec(BaseModel):
    """Specification for a single paper section to be drafted independently."""

    model_config = ConfigDict(frozen=True)

    heading: str
    level: int = Field(ge=1, le=4)
    word_count_target: int = Field(ge=0)
    purpose: str
    content_guidance: str
    key_sources: list[str] = Field(default_factory=list)
    argument_chain: CERChain | None = None
    adjacent_context: str = Field(default="")


class ArgumentBlueprint(BaseModel):
    """Argument blueprint from the argument builder agent."""

    model_config = ConfigDict(frozen=True)

    central_thesis: str = Field(description="Central thesis or argument")
    sub_arguments: list[CERChain] = Field(
        default_factory=list, description="Claim-evidence-reasoning chains per section"
    )
    evidence_map: dict[str, list[str]] = Field(
        default_factory=dict, description="Evidence sources mapped to claims"
    )
    counter_arguments: list[str] = Field(
        default_factory=list, description="Anticipated counter-arguments"
    )
    logical_flow: str = Field(default="", description="Description of argument progression")
    overall_strength: str = Field(
        default="adequate", description="Overall argument strength assessment"
    )


class CitationCorrection(BaseModel):
    """A single citation correction."""

    model_config = ConfigDict(frozen=True)

    location: str = Field(description="Where the error was found")
    error: str = Field(description="Description of the citation error")
    correction: str = Field(description="What was corrected to")


class CitationAudit(BaseModel):
    """Citation compliance audit from the citation compliance agent."""

    model_config = ConfigDict(frozen=True)

    total_citations: int = Field(ge=0, description="Total citations found")
    valid_citations: int = Field(ge=0, description="Citations passing validation")
    corrections: list[CitationCorrection] = Field(
        default_factory=list, description="Citation corrections applied"
    )
    orphan_in_text: int = Field(ge=0, default=0, description="In-text citations with no reference entry")
    orphan_references: int = Field(ge=0, default=0, description="Reference entries not cited in text")
    format_errors_corrected: int = Field(ge=0, default=0, description="Number of format errors corrected")
    missing_dois: int = Field(ge=0, default=0, description="Number of references missing DOIs")
    format_compliance: float = Field(
        ge=0.0, le=1.0, description="Fraction of citations in correct format"
    )
    corrected_text: str = Field(default="", description="Full text with corrections applied")
    recommendations: list[str] = Field(
        default_factory=list, description="Fix recommendations"
    )


class AbstractOutput(BaseModel):
    """Abstract generated by the abstract agent."""

    model_config = ConfigDict(frozen=True)

    abstract_text: str = Field(description="Generated abstract text")
    word_count: int = Field(ge=0, description="Abstract word count")
    keywords: list[str] = Field(default_factory=list, description="Extracted keywords")
    structured: bool = Field(
        default=False, description="Whether the abstract uses structured headings"
    )


class Figure(BaseModel):
    """A single figure with caption, code, and placement."""

    model_config = ConfigDict(frozen=True)

    figure_number: int = Field(ge=1, description="Figure number")
    caption: str = Field(description="Full figure caption")
    code_language: str = Field(default="python", description="Python or R")
    code: str = Field(default="", description="Runnable code to generate figure")
    # Source PNG already produced by the Dagster experiment workspace.
    # When set, the figure is included via \includegraphics — no sandbox
    # execution. When None (legacy path), `code` is used.
    source_path: Path | None = Field(
        default=None,
        description="Pre-rendered PNG path from Dagster experiment workspace; when set, takes precedence over `code`.",
    )
    data_source: str = Field(default="", description="Data source description")
    placement: str = Field(default="", description="Recommended placement")


class Table(BaseModel):
    """A single table with caption metadata and optional row data."""

    model_config = ConfigDict(frozen=True)

    table_number: str = Field(description="Table number (e.g. '1', 'A.1')")
    title: str = Field(description="Brief table title")
    caption: str = Field(default="", description="Full APA caption text")
    placement: str = Field(default="", description="Recommended placement (e.g. 'Section 4.1')")
    headers: list[str] = Field(default_factory=list, description="Column headers")
    rows: list[list[str]] = Field(
        default_factory=list,
        description="Row data; each row matches header length when headers is non-empty",
    )


class FigurePackage(BaseModel):
    """Visualization package from the visualization agent."""

    model_config = ConfigDict(frozen=True)

    figures: list[Figure] = Field(
        default_factory=list, description="Figure specifications with captions"
    )
    tables: list[Table] = Field(
        default_factory=list,
        description="Table specifications with captions and optional row data",
    )
    placement_notes: str = Field(default="", description="Notes on figure/table placement")


class FormattedPaper(BaseModel):
    """Final formatted paper from the formatter agent."""

    model_config = ConfigDict(frozen=True)

    formatted_content: str = Field(description="Fully formatted paper content")
    format_type: str = Field(description="LaTeX / Markdown / DOCX / Plain")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Paper metadata (title, authors, etc.)"
    )
    submission_checklist: list[str] = Field(
        default_factory=list, description="Pre-submission checklist items"
    )


class SentenceLength(BaseModel):
    """Statistical profile of sentence length distribution."""

    model_config = ConfigDict(frozen=True)

    mean: float
    stddev: float
    rhythm_pattern: str = ""


class ParagraphLength(BaseModel):
    """Statistical profile of paragraph length in sentences."""

    model_config = ConfigDict(frozen=True)

    mean_sentences: float
    variation: str = ""


class VocabularyPreferences(BaseModel):
    """Preferred vocabulary choices including hedging, transitions, and formality level."""

    model_config = ConfigDict(frozen=True)

    hedging_words: list[str] = Field(default_factory=list)
    transition_words: list[str] = Field(default_factory=list)
    preferred_verbs: list[str] = Field(default_factory=list)
    formality: str = "moderate-formal"


class CitationStyleMetrics(BaseModel):
    """Quantitative metrics for in-text citation usage patterns."""

    model_config = ConfigDict(frozen=True)

    narrative_ratio: float = Field(ge=0.0, le=1.0)
    parenthetical_ratio: float = Field(ge=0.0, le=1.0)
    density: float = Field(ge=0.0)
    placement: str = "mixed"


class RegisterShift(BaseModel):
    """Assertiveness level variation for a specific paper section."""

    model_config = ConfigDict(frozen=True)

    section_name: str
    assertiveness_level: str


class StyleProfile(BaseModel):
    """Author writing style profile calibrated from sample texts."""

    model_config = ConfigDict(frozen=True)

    calibration_source: list[str]
    sample_count: int = Field(ge=1)
    sentence_length: SentenceLength
    paragraph_length: ParagraphLength
    vocabulary_preferences: VocabularyPreferences
    citation_style: CitationStyleMetrics
    modifier_style: ModifierStyle = "moderate"
    register_shifts: list[RegisterShift] = Field(default_factory=list)

    conflicts_with_discipline: list[str] | None = None
    partial_profile: bool | None = None
    language_mismatch: bool | None = None
