"""Models for the cascaded reviewer pipeline (SCI Spec 6 Phase 1).

The cascaded review composes Specs 1, 4, 5 into a structured 4-stage gate
sequence. Each stage is a gate; failure short-circuits subsequent stages.

Stage A — Numerical grounding (Spec 1 + numerical_claims_auditor agent)
Stage B — Novelty (Spec 4 PointWiseNovelty)
Stage C — Methodology (Spec 5 persona reviewers)
Stage D — Narrative quality (existing narrative scoring)

The cascade pattern is what gives DeepReviewer-14B its adversarial robustness
(only 0.31 score shift under attack vs >2 for one-shot reviewers).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CascadeStageName(StrEnum):
    """The four cascade stage identifiers, in run order."""

    NUMERICAL_GROUNDING = "numerical_grounding"
    NOVELTY = "novelty"
    METHODOLOGY = "methodology"
    NARRATIVE = "narrative"


class StageVerdict(StrEnum):
    """Per-stage outcome.

    PASS — stage ran and the gate did not reject.
    SHORT_CIRCUIT_REJECT — stage ran and rejected; downstream stages SKIPPED.
    SKIPPED — stage was not run because an earlier stage rejected.
    NOT_RUN — stage was not run because its upstream feature flag is off.
    """

    PASS = "pass"
    SHORT_CIRCUIT_REJECT = "short_circuit_reject"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


class StageResult(BaseModel):
    """Result for one cascade stage."""

    model_config = ConfigDict(frozen=True)

    stage: CascadeStageName
    verdict: StageVerdict
    gate_reason: str | None = None
    """Explanation if SHORT_CIRCUIT_REJECT, else None."""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    """Opaque underlying review output (e.g. NoveltyReport for stage B)."""


class CascadeResult(BaseModel):
    """Final aggregated cascade result.

    `stages` always contains one entry per stage that was visited (in order);
    SKIPPED entries are present for stages downstream of a rejection.
    """

    model_config = ConfigDict(frozen=True)

    stages: list[StageResult]
    final_verdict: Literal["accept", "minor_revision", "major_revision", "reject"]
    rejection_stage: CascadeStageName | None = None
    rejection_summary: str = ""


class ClaimAuditFinding(BaseModel):
    """One numerical-claim audit finding from the numerical_claims_auditor agent."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    """Identifier of the form A1, A2, ...."""
    severity: Literal["critical", "major", "minor"]
    description: str
    """What the issue is (e.g. 'value 23.5% in Results not in trace store')."""
    offending_text: str = ""
    """The bare-number prose snippet that triggered the finding (best-effort)."""
    expected_label: str | None = None
    """If the auditor inferred a likely store label, the label name."""


class ClaimAuditReport(BaseModel):
    """Structured output from the numerical_claims_auditor agent."""

    model_config = ConfigDict(frozen=True)

    findings: list[ClaimAuditFinding] = Field(default_factory=list)
    overall_grounding_pass: bool
    """True when no critical findings; downstream stages may proceed."""
    summary: str = ""
