"""Models for the persona-anchored reviewer panel (SCI Spec 5 Phase 1).

Persona-anchored reviewers are parameterized along three behavioral axes
from AgentReview (https://arxiv.org/abs/2406.12708):

- ``commitment``: how seriously the reviewer engages
- ``intention``: motive (gatekeeper, practitioner, advocate, purist)
- ``knowledgeability``: depth in the subject

Each persona reviewer outputs a structured ``PersonaReviewOutput`` that
includes the persona stamp and structured findings. The editorial
synthesizer (Phase 2) will apply persona-aware aggregation rules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Commitment(StrEnum):
    """How seriously the reviewer engages with the manuscript."""

    THOROUGH = "thorough"
    SUPERFICIAL = "superficial"


class Intention(StrEnum):
    """The reviewer's motive, framed as a behavioral default."""

    SKEPTICAL_GATEKEEPER = "skeptical_gatekeeper"
    """Default verdict is reject; manuscript must convince otherwise."""
    APPLIED_PRACTITIONER = "applied_practitioner"
    """Asks 'is this usable in my practice tomorrow?'"""
    ENTHUSIASTIC_ADVOCATE = "enthusiastic_advocate"
    """Tries to find publishable contributions."""
    DOMAIN_PURIST = "domain_purist"
    """Checks methodological orthodoxy; rejects deviations."""


class Knowledgeability(StrEnum):
    """The reviewer's depth in the subject area."""

    DEEP_IN_FIELD = "deep_in_field"
    ADJACENT_FIELD = "adjacent_field"
    NOVICE = "novice"


class PersonaSpec(BaseModel):
    """Three-axis persona stamp attached to every persona reviewer's output."""

    model_config = ConfigDict(frozen=True)

    commitment: Commitment
    intention: Intention
    knowledgeability: Knowledgeability
    target_journal: str
    """Human-readable journal name the reviewer is acting on behalf of."""
    target_acceptance_rate: float = Field(ge=0.0, le=1.0)
    """0.20 = the reviewer rejects 80% of papers they review."""


class ReviewFinding(BaseModel):
    """One atomic finding from a persona reviewer."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    """Identifier of the form F1, F2, ...."""
    severity: Literal["critical", "major", "minor", "suggestion"]
    section: str
    description: str
    rejection_grounds: bool
    """True if this finding alone justifies rejection."""


class PersonaReviewOutput(BaseModel):
    """Structured output from a single persona-anchored reviewer."""

    model_config = ConfigDict(frozen=True)

    persona: PersonaSpec
    findings: list[ReviewFinding] = Field(default_factory=list)
    overall_verdict: Literal["accept", "minor_revision", "major_revision", "reject"]
    confidence: float = Field(ge=0.0, le=1.0)
    one_paragraph_summary: str
