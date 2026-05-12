"""Shared domain models used across multiple pipeline subgraphs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    # Type aliases — research
    "FlaggedSeverity",
    "SourceType",
    "QualityTier",
    "Relevance",
    # Type aliases — writing
    "CitationFormat",
    "StructureType",
    "ArgumentStrength",
    "ModifierStyle",
    # Type aliases — review
    "WeaknessType",
    "WeaknessSeverity",
    "ConsensusLevel",
    "ItemType",
    "Priority",
    "ResponseStatus",
    # Type aliases — integrity
    "IssueSeverity",
    "IntegrityVerdict",
    "VerificationStatus",
    # Constants
    "PASSPORT_FRESHNESS_HOURS",
    # Cross-domain models
    "Source",
    "Author",
    "Reference",
    "EvaluatorDetail",
    "EvaluationResult",
]


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# Research
FlaggedSeverity = Literal["Low", "Medium", "High", "Critical"]
SourceType = Literal[
    "journal_article",
    "book",
    "chapter",
    "conference",
    "report",
    "thesis",
    "preprint",
    "web",
]
QualityTier = Literal["tier_1", "tier_2", "tier_3", "tier_4"]
Relevance = Literal["core", "supporting", "peripheral"]

# Writing
CitationFormat = Literal["APA7", "Chicago", "MLA", "IEEE", "Vancouver"]
StructureType = Literal[
    "IMRaD",
    "literature_review",
    "theoretical",
    "case_study",
    "policy_brief",
    "conference",
]
ArgumentStrength = Literal["compelling", "strong", "adequate", "weak"]
ModifierStyle = Literal["minimal", "moderate", "elaborate"]

# Review
WeaknessType = Literal["methodology", "theory", "evidence", "writing", "structure", "ethics"]
WeaknessSeverity = Literal["critical", "major", "minor"]
ConsensusLevel = Literal["CONSENSUS-4", "CONSENSUS-3", "SPLIT", "DA-CRITICAL"]
ItemType = Literal["Major", "Minor", "Editorial"]
Priority = Literal["must_fix", "should_fix", "consider"]
ResponseStatus = Literal["RESOLVED", "DELIBERATE_LIMITATION", "UNRESOLVABLE", "REVIEWER_DISAGREE"]

# Integrity
IssueSeverity = Literal["SERIOUS", "MEDIUM", "MINOR"]
IntegrityVerdict = Literal["PASS", "PASS_WITH_CONDITIONS", "FAIL"]
VerificationStatus = Literal["VERIFIED", "UNVERIFIED", "STALE"]

PASSPORT_FRESHNESS_HOURS = 24


# ---------------------------------------------------------------------------
# Cross-domain models
# ---------------------------------------------------------------------------


class Source(BaseModel):
    """Single bibliographic source with quality and relevance metadata."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    id: str
    title: str
    authors: list[str]
    year: int
    doi: str | None = None
    citation: str
    source_type: SourceType = Field(alias="type")
    evidence_tier: int = Field(ge=1, le=7)
    quality_tier: QualityTier
    relevance: Relevance
    relevance_score: int = Field(ge=1, le=10)
    annotation: str

    verified: bool | None = None
    retraction_check: bool | None = None


class Author(BaseModel):
    """Paper author with affiliation and CRediT contribution roles."""

    model_config = ConfigDict(frozen=True)

    name: str
    affiliation: str
    email: str = ""
    credit_roles: list[str] = Field(default_factory=list)
    corresponding: bool = False


class Reference(BaseModel):
    """Formatted reference entry with cross-references to citing sections."""

    model_config = ConfigDict(frozen=True)

    id: str
    full_citation: str
    doi: str | None = None
    cited_in_sections: list[str] = Field(default_factory=list)


class EvaluatorDetail(BaseModel):
    """Individual evaluator model's scores and feedback."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    scores: dict[str, float] = Field(default_factory=dict)
    feedback: str = ""


class EvaluationResult(BaseModel):
    """Output from the 3-model evaluation panel for per-node quality gating."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["PASS", "NEEDS_IMPROVEMENT"]
    scores: dict[str, float] = Field(description="Dimension name to median score (0-10)")
    feedback: str = Field(description="Merged feedback from all evaluators")
    weakest_dimension: str | None = None
    per_model: list[EvaluatorDetail] = Field(default_factory=list, description="Individual evaluator results")
