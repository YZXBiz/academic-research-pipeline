"""Integrity-phase domain models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from academic_pipeline.models.shared import (
    PASSPORT_FRESHNESS_HOURS,
    IntegrityVerdict,
    IssueSeverity,
    VerificationStatus,
)
from academic_pipeline.core.enums import IssueSeverity as IssueSeverityEnum

__all__ = [
    "IntegrityFailureMode",
    "IntegrityVerificationOutput",
    "ComplianceItemResult",
    "ComplianceReport",
    "FailureModeResult",
    "IntegrityIssue",
    "CitationContextIssue",
    "DataIssue",
    "OriginalityIssue",
    "ClaimDistortion",
    "PhaseAReferences",
    "PhaseBCitationContext",
    "PhaseCData",
    "PhaseDOriginality",
    "PhaseEClaims",
    "PhaseResult",
    "IssueCounts",
    "IntegrityReport",
    "MaterialPassport",
]


class IntegrityFailureMode(BaseModel):
    """Single AI research failure mode check result."""

    model_config = ConfigDict(frozen=True)

    mode_id: str = Field(description="Failure mode ID (e.g., FM1, FM2)")
    name: str = Field(description="Failure mode name (e.g., Circular Validation)")
    verdict: str = Field(description="PASS, FLAGGED, or SKIPPED")
    severity: str = Field(default="NONE", description="NONE, MINOR, MAJOR, or CRITICAL")
    evidence: str = Field(default="", description="Evidence supporting the verdict")


class IntegrityVerificationOutput(BaseModel):
    """Structured output from the integrity verification agent."""

    model_config = ConfigDict(frozen=True)

    verdict: str = Field(description="PASS, PASS WITH NOTES, or FAIL")
    summary: str = Field(description="Brief summary of integrity findings")
    report: str = Field(description="Full integrity verification report in markdown")
    failure_modes: list[IntegrityFailureMode] = Field(default_factory=list)


class ComplianceItemResult(BaseModel):
    """Single PRISMA-trAIce checklist item evaluation result."""

    model_config = ConfigDict(frozen=True)

    item_id: str = Field(description="Checklist item ID (e.g., M1, T1)")
    item_name: str = Field(description="Checklist item name")
    tier: Literal["mandatory", "highly_recommended", "recommended", "optional"] = Field(
        description="Item tier determining block behavior"
    )
    verdict: Literal["pass", "fail", "not_applicable"] = Field(description="Evaluation result")
    evidence: str = Field(description="What was found in the paper")
    reason: str = Field(description="Why the item passed or failed")


class ComplianceReport(BaseModel):
    """Output from the PRISMA-trAIce compliance agent."""

    model_config = ConfigDict(frozen=True)

    stage: Literal["2.5", "4.5"] = Field(description="Integrity gate stage")
    items: list[ComplianceItemResult] = Field(description="Per-item evaluation results")
    block_decision: Literal["block", "warn", "pass"] = Field(description="Overall decision")
    summary: str = Field(description="Brief summary of compliance findings")


class FailureModeResult(BaseModel):
    """Result of a single AI research failure mode check."""

    model_config = ConfigDict(frozen=True)

    mode_id: int = Field(ge=1, le=7)
    name: str
    verdict: Literal["PASS", "FLAGGED", "SKIPPED"]
    severity: IssueSeverityEnum | None = None
    evidence: str = ""


class IntegrityIssue(BaseModel):
    """Reference integrity issue found during verification."""

    model_config = ConfigDict(frozen=True)

    ref_id: str = ""
    issue_type: str = ""
    severity: IssueSeverity = "MINOR"
    detail: str = ""


class CitationContextIssue(BaseModel):
    """Mismatch between a citation's context and its source content."""

    model_config = ConfigDict(frozen=True)

    ref_id: str
    section: str
    issue: str


class DataIssue(BaseModel):
    """Discrepancy between a claimed value and its actual value."""

    model_config = ConfigDict(frozen=True)

    claim: str
    expected: str
    actual: str
    severity: IssueSeverity


class OriginalityIssue(BaseModel):
    """Originality or plagiarism concern identified during integrity review."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    issue_type: str = Field(alias="type")
    severity: IssueSeverity
    detail: str


class ClaimDistortion(BaseModel):
    """Distortion of a source's claim detected during verification."""

    model_config = ConfigDict(frozen=True)

    claim: str
    source: str
    verdict: str
    detail: str


class PhaseAReferences(BaseModel):
    """Phase A results: reference existence and format verification."""

    model_config = ConfigDict(frozen=True)

    checked: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    issues: list[IntegrityIssue] = Field(default_factory=list)


class PhaseBCitationContext(BaseModel):
    """Phase B results: citation-context accuracy sampling."""

    model_config = ConfigDict(frozen=True)

    sampled: int = Field(ge=0)
    verified: int = Field(ge=0)
    issues: list[CitationContextIssue] = Field(default_factory=list)


class PhaseCData(BaseModel):
    """Phase C results: data and statistical claim verification."""

    model_config = ConfigDict(frozen=True)

    claims_checked: int = Field(ge=0)
    verified: int = Field(ge=0)
    issues: list[DataIssue] = Field(default_factory=list)


class PhaseDOriginality(BaseModel):
    """Phase D results: originality and plagiarism check."""

    model_config = ConfigDict(frozen=True)

    checked: bool = False
    issues: list[OriginalityIssue] = Field(default_factory=list)


class PhaseEClaims(BaseModel):
    """Phase E results: source claim distortion detection."""

    model_config = ConfigDict(frozen=True)

    checked: int = Field(ge=0)
    verified: int = Field(ge=0)
    distortions: list[ClaimDistortion] = Field(default_factory=list)


class PhaseResult(BaseModel):
    """Combined results from all five integrity check phases (A through E)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    references: PhaseAReferences = Field(alias="A_references")
    citation_context: PhaseBCitationContext = Field(alias="B_citation_context")
    data: PhaseCData = Field(alias="C_data")
    originality: PhaseDOriginality = Field(alias="D_originality")
    claims: PhaseEClaims = Field(alias="E_claims")


class IssueCounts(BaseModel):
    """Aggregate issue counts grouped by severity level."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    serious: int = Field(ge=0, default=0, alias="SERIOUS")
    medium: int = Field(ge=0, default=0, alias="MEDIUM")
    minor: int = Field(ge=0, default=0, alias="MINOR")


class IntegrityReport(BaseModel):
    """Full integrity check report with verdict, phase results, and risk scores."""

    model_config = ConfigDict(frozen=True)

    verdict: IntegrityVerdict
    phase: str = "preint"
    phases: PhaseResult
    overall_issues: IssueCounts
    citation_integrity_score: float = Field(ge=0.0, le=1.0)
    fabrication_risk_score: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def blocks_pipeline(self) -> bool:
        """Return whether any serious or medium issues block the pipeline."""
        return self.overall_issues.serious > 0 or self.overall_issues.medium > 0


class MaterialPassport(BaseModel):
    """Provenance and verification record for a pipeline artifact."""

    model_config = ConfigDict(frozen=True)

    origin_skill: str
    origin_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verification_status: VerificationStatus = "UNVERIFIED"
    version_label: str

    integrity_pass_date: datetime | None = None
    content_hash: str | None = None
    upstream_dependencies: list[str] = Field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        """Return whether the integrity pass has expired or was never set."""
        if self.integrity_pass_date is None:
            return True
        threshold = datetime.now(UTC) - timedelta(hours=PASSPORT_FRESHNESS_HOURS)
        return self.integrity_pass_date < threshold

    @property
    def can_skip_pre_review_integrity(self) -> bool:
        """Return whether the artifact may skip pre-review integrity checks."""
        return self.verification_status == "VERIFIED" and not self.is_stale
