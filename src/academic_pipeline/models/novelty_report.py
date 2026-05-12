"""Models for the point-wise novelty reviewer (SCI Spec 4 Phase 1).

The point-wise novelty reviewer extracts atomic contribution claims from a
finished manuscript and verdicts each one against retrieved Semantic Scholar
prior works. Verdicts are aggregated into a NoveltyReport with overall
verdict in {PASS, REVISE, REJECT_NOVELTY}.

Reuses NeighborPaper from models/novelty_gate.py.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from academic_pipeline.models.novelty_gate import NeighborPaper


class ClaimNoveltyDimension(StrEnum):
    """The kind of novelty a contribution claim asserts."""

    NEW_CONCEPT = "new_concept"
    NEW_METHOD = "new_method"
    NEW_APPLICATION = "new_application"
    NEW_DATASET = "new_dataset"
    NEW_RESULT = "new_result"


class ClaimVerdict(StrEnum):
    """Per-claim novelty verdict against retrieved prior works."""

    REDUNDANT = "redundant"
    """This exact contribution exists in one of the prior works."""
    PARTIAL_OVERLAP = "partial_overlap"
    """Similar work exists; our claim has identifiable differentiation."""
    NOVEL = "novel"
    """No overlapping prior work found in the retrieved set."""


class ContributionClaim(BaseModel):
    """One atomic contribution claim extracted from the manuscript."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    """Identifier of the form C1, C2, ...."""
    claim_text: str
    """Free-text claim, of form "<X> is novel because <Y>"."""
    dimension: ClaimNoveltyDimension
    section: str
    """Manuscript section the claim appears in (e.g. 'introduction', 'results')."""
    cited_traces: list[str] = Field(default_factory=list)
    """⟨num:label⟩ trace tokens this claim cites (from Spec 1). Empty if qualitative."""


class ContributionClaimList(BaseModel):
    """Wrapper for PromptedOutput on the claim_extractor agent."""

    model_config = ConfigDict(frozen=True)

    claims: list[ContributionClaim]


class ClaimAssessment(BaseModel):
    """Per-claim novelty assessment against retrieved prior works."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    verdict: ClaimVerdict
    nearest_prior_works: list[NeighborPaper] = Field(default_factory=list)
    differentiation_note: str
    """1-2 sentences justifying the verdict, citing the closest prior work by title."""


class NoveltyReport(BaseModel):
    """Aggregated point-wise novelty review result."""

    model_config = ConfigDict(frozen=True)

    claims: list[ContributionClaim]
    assessments: list[ClaimAssessment]
    overall_verdict: Literal["PASS", "REVISE", "REJECT_NOVELTY"]
    rejection_blockers: list[str] = Field(default_factory=list)
    """claim_ids of REDUNDANT claims that triggered REJECT_NOVELTY."""
