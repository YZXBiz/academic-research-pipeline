"""Review-phase domain models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from academic_pipeline.models.shared import (
    ConsensusLevel,
    ItemType,
    Priority,
    ResponseStatus,
    WeaknessSeverity,
    WeaknessType,
)
from academic_pipeline.core.enums import (
    EditorialDecision,
    ReviewDimension,
    RevisionSource,
)
from academic_pipeline.core.enums import IssueSeverity as IssueSeverityEnum

__all__ = [
    "PeerReviewDimensionScores",
    "PeerReviewOutput",
    "FigureVerification",
    "FigureVerificationReport",
    "PeerReviewComment",
    "PeerReviewReport",
    "ReviewerConfigCard",
    "FieldAnalysis",
    "EICReview",
    "EditorialSynthesis",
    "DimensionScore",
    "Weakness",
    "ReviewerReport",
    "RoadmapItem",
    "ReviewReport",
    "RevisionRoadmap",
    "ResponseItem",
    "ResponseToReviewers",
    "EditorDimensionScore",
    "ReviewIssue",
    "EditorReview",
    "RevisionContext",
]


class PeerReviewDimensionScores(BaseModel):
    """Dimension scores from peer review."""

    model_config = ConfigDict(frozen=True)

    originality: float = Field(description="Score out of 10 for novel contribution")
    methodological_rigor: float = Field(description="Score out of 10 for method validity")
    evidence_sufficiency: float = Field(description="Score out of 10 for claims supported by data")
    argument_coherence: float = Field(description="Score out of 10 for logical flow")
    writing_quality: float = Field(description="Score out of 10 for clarity and format")


class PeerReviewOutput(BaseModel):
    """Structured output from the peer reviewer agent."""

    model_config = ConfigDict(frozen=True)

    decision: str = Field(description="Accept, Minor Revision, Major Revision, or Reject")
    overall_score: float = Field(description="Weighted overall score out of 10")
    dimension_scores: PeerReviewDimensionScores
    summary: str = Field(description="Brief summary of peer review findings")
    report: str = Field(description="Full peer review report in markdown")


class FigureVerification(BaseModel):
    """Single figure verification result."""

    model_config = ConfigDict(frozen=True)

    figure_id: str = Field(description="Figure identifier")
    score: int = Field(ge=0, le=10, description="Score out of 10 checklist points")
    issues: list[str] = Field(default_factory=list, description="Specific problems found")
    suggestions: list[str] = Field(default_factory=list, description="How to fix issues")


class FigureVerificationReport(BaseModel):
    """Output from VLM figure verification."""

    model_config = ConfigDict(frozen=True)

    figures: list[FigureVerification] = Field(default_factory=list)
    all_pass: bool = Field(description="True if all figures score >= 8")
    summary: str = Field(description="Brief assessment of figure quality")


class PeerReviewComment(BaseModel):
    """A detailed review comment on a specific aspect."""

    model_config = ConfigDict(frozen=True)

    aspect: str = Field(description="The aspect being reviewed")
    comment: str = Field(description="The reviewer's assessment")


class PeerReviewReport(BaseModel):
    """Structured peer review report shared by methodology, domain, and perspective reviewers."""

    model_config = ConfigDict(frozen=True)

    reviewer_identity: str = Field(description="Description of reviewer's configured identity")
    overall_recommendation: str = Field(description="Accept / Minor Revision / Major Revision / Reject")
    confidence_score: int = Field(ge=1, le=5, description="Reviewer confidence in assessment")
    summary_assessment: str = Field(description="150-250 word summary of the review")
    strengths: list[str] = Field(min_length=1, max_length=5, description="Key strengths identified")
    weaknesses: list[str] = Field(min_length=1, max_length=5, description="Key weaknesses with improvement suggestions")
    detailed_comments: list[PeerReviewComment] = Field(description="Section-by-section detailed feedback")
    questions_for_authors: list[str] = Field(default_factory=list, description="Questions requiring author response")
    minor_issues: list[str] = Field(default_factory=list, description="Minor text/formatting issues")


class ReviewerConfigCard(BaseModel):
    """Configuration card for a peer reviewer."""

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="Reviewer role")
    identity_description: str = Field(description="Detailed identity for this reviewer")
    review_focus: list[str] = Field(min_length=1, max_length=5, description="Key focus areas")
    will_care_about: str = Field(description="What this reviewer will particularly scrutinize")
    possible_blind_spots: str = Field(description="Potential blind spots")


class FieldAnalysis(BaseModel):
    """Field analysis output from the field analyst agent."""

    model_config = ConfigDict(frozen=True)

    primary_discipline: str = Field(description="Primary academic discipline")
    secondary_disciplines: list[str] = Field(default_factory=list, description="Related disciplines")
    research_paradigm: str = Field(description="Positivist / Interpretivist / Pragmatist / Critical")
    methodology_type: str = Field(description="Qualitative / Quantitative / Mixed / Theoretical")
    target_journal_tier: str = Field(description="Q1 / Q2 / Q3 / Q4")
    paper_maturity: str = Field(description="first_draft / revised / pre-submission")
    recommended_journals: list[str] = Field(min_length=1, max_length=5, description="Recommended journals")
    reviewer_config_cards: list[ReviewerConfigCard] = Field(description="Config cards for peer reviewers")
    review_strategy: str = Field(description="Overall review strategy recommendations")


class EICReview(BaseModel):
    """EIC review in the review subgraph."""

    model_config = ConfigDict(frozen=True)

    overall_recommendation: str = Field(description="Accept / Minor Revision / Major Revision / Reject")
    confidence_score: int = Field(ge=1, le=5, description="EIC confidence in recommendation")
    summary_assessment: str = Field(description="150-250 word overall assessment")
    strengths: list[str] = Field(min_length=1, max_length=5, description="Major strengths")
    weaknesses: list[str] = Field(min_length=1, max_length=5, description="Major weaknesses with suggestions")
    detailed_comments: list[PeerReviewComment] = Field(description="Comments on journal fit, originality, etc.")
    questions_for_authors: list[str] = Field(default_factory=list, description="Questions for authors")
    minor_issues: list[str] = Field(default_factory=list, description="Minor issues noted")
    recommendation_to_peer_reviewers: str = Field(description="Guidance for peer reviewers")


class EditorialSynthesis(BaseModel):
    """Structured output from the editorial synthesizer agent."""

    model_config = ConfigDict(frozen=True)

    decision: str = Field(description="Accept, Minor Revision, Major Revision, or Reject")
    summary: str = Field(description="Brief decision rationale")
    report: str = Field(description="Full editorial decision package in markdown")


class DimensionScore(BaseModel):
    """Weighted score for a single review evaluation dimension."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    weight: float = Field(ge=0.0, le=1.0)
    score: int = Field(ge=0, le=100)


class Weakness(BaseModel):
    """Identified weakness in a manuscript with severity and category."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    description: str
    severity: WeaknessSeverity
    weakness_type: WeaknessType = Field(alias="type")


class ReviewerReport(BaseModel):
    """Single reviewer's evaluation including scores, strengths, and weaknesses."""

    model_config = ConfigDict(frozen=True)

    reviewer_id: str
    role: str
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[Weakness] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=1, le=5, default=3)


class RoadmapItem(BaseModel):
    """Single actionable revision item from peer review feedback."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str
    description: str
    reviewer: str
    item_type: ItemType = Field(alias="type")
    priority: Priority
    target_section: str
    suggested_action: str
    consensus_level: ConsensusLevel
    verification_criteria: str


class ReviewReport(BaseModel):
    """Aggregated peer review report with editorial decision and consensus level."""

    model_config = ConfigDict(frozen=True)

    editorial_decision: EditorialDecision
    reviewer_reports: list[ReviewerReport]
    consensus: ConsensusLevel
    revision_roadmap: list[RoadmapItem] = Field(default_factory=list)
    confidence_score: int = Field(ge=0, le=100)

    def weighted_score(self) -> float:
        """Return the weighted average score across all reviewer dimensions."""
        total_weight = 0.0
        weighted_sum = 0.0
        for report in self.reviewer_reports:
            for ds in report.dimension_scores:
                weighted_sum += ds.score * ds.weight
                total_weight += ds.weight
        return weighted_sum / total_weight if total_weight > 0 else 0.0


class RevisionRoadmap(BaseModel):
    """Prioritized list of revision items derived from peer review."""

    model_config = ConfigDict(frozen=True)

    items: list[RoadmapItem]
    total_items: int = Field(ge=0)
    must_fix_count: int = Field(ge=0)
    editorial_decision: EditorialDecision
    consensus_summary: str
    dissenting_opinions: list[str] = Field(default_factory=list)

    deadline_suggestion: str | None = None


class ResponseItem(BaseModel):
    """Author's point-by-point response to a single reviewer comment."""

    model_config = ConfigDict(frozen=True)

    roadmap_item_id: str
    reviewer_comment: str
    author_response: str
    change_location: str
    status: ResponseStatus
    decline_justification: str | None = None

    @model_validator(mode="after")
    def check_justification(self) -> ResponseItem:
        """Validate that non-resolved statuses include a decline justification."""
        needs_justification = {"DELIBERATE_LIMITATION", "UNRESOLVABLE", "REVIEWER_DISAGREE"}
        if self.status in needs_justification and not self.decline_justification:
            raise ValueError(f"decline_justification is required when status is {self.status}")
        return self


class ResponseToReviewers(BaseModel):
    """Complete response-to-reviewers document for a revision round."""

    model_config = ConfigDict(frozen=True)

    revision_round: int = Field(ge=1)
    items: list[ResponseItem]
    word_count_delta: int = 0
    new_references_added: int = Field(ge=0, default=0)
    summary_of_changes: str = ""
    new_content_highlight: list[str] = Field(default_factory=list)

    def _count_by_status(self, status: ResponseStatus) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def resolved_count(self) -> int:
        """Count of items with RESOLVED status."""
        return self._count_by_status("RESOLVED")

    @property
    def limitations_count(self) -> int:
        """Count of items with DELIBERATE_LIMITATION status."""
        return self._count_by_status("DELIBERATE_LIMITATION")

    @property
    def unresolvable_count(self) -> int:
        """Count of items with UNRESOLVABLE status."""
        return self._count_by_status("UNRESOLVABLE")

    @property
    def disagreed_count(self) -> int:
        """Count of items with REVIEWER_DISAGREE status."""
        return self._count_by_status("REVIEWER_DISAGREE")


class EditorDimensionScore(BaseModel):
    """Single dimension score from editor-in-chief review."""

    model_config = ConfigDict(frozen=True)

    dimension: ReviewDimension = Field(description="Which dimension this score covers")
    score: float = Field(ge=1.0, le=5.0, description="Score for this dimension (1-5)")
    weight: float = Field(ge=0.0, le=1.0, description="Weight of this dimension in overall score")
    notes: str = Field(description="Justification for this score")


class ReviewIssue(BaseModel):
    """Categorized issue from editor or DA review."""

    model_config = ConfigDict(frozen=True)

    severity: IssueSeverityEnum = Field(description="critical, major, minor, or suggestion")
    dimension: ReviewDimension = Field(description="Which review dimension this issue affects")
    description: str = Field(description="What the issue is")
    recommendation: str = Field(description="Specific actionable fix")


class EditorReview(BaseModel):
    """Structured output from the editor-in-chief agent."""

    model_config = ConfigDict(frozen=True)

    verdict: EditorialDecision
    weighted_score: float = Field(ge=0.0, le=5.0, description="Overall weighted score (1-5)")
    dimensions: list[EditorDimensionScore]
    issues: list[ReviewIssue]
    strengths: list[str] = Field(description="Specific strengths of the paper")
    summary: str = Field(description="Brief editorial summary")


class RevisionContext(BaseModel):
    """Feedback + previous output passed into revision runs."""

    model_config = ConfigDict(frozen=True)

    round: int = Field(ge=1, description="Revision round number")
    source: RevisionSource
    target_node: str = Field(description="Name of the node being asked to revise")
    weakest_dimension: ReviewDimension
    feedback_summary: str = Field(description="Summary of what needs to be improved")
    issues: list[ReviewIssue]
    previous_output: str = Field(description="The full previous output to revise from")
