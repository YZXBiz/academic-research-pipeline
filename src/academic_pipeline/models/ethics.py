"""Structured 12-item ethics checklist (PRISMA-trAIce + COI + AI-disclosure).

Replaces the freeform ``EthicsReviewOutput`` with a checklist of yes/no items
each requiring justification. Used by :class:`EthicsChecklistNode` in the
integrity subgraph (PRD §6.5.T1; the legacy research-side ``EthicsReviewNode``
was deleted in §6.1.T6).

Spec: ``docs/superpowers/specs/2026-05-03-checklist-ethics-design.md``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Canonical names of the 12 standard checklist items, in canonical order.
# The output validator in :mod:`academic_pipeline.research.ethics_validator`
# rejects any checklist whose ``items[*].name`` does not match this tuple
# exactly.
STANDARD_ITEMS: tuple[str, ...] = (
    "human_subjects_disclosed",
    "irb_approval_documented",
    "informed_consent_documented",
    "data_provenance_traced",
    "data_use_license_compliant",
    "coi_disclosed",
    "structural_coi_absent",
    "ai_assistance_disclosed",
    "reproducibility_artifacts_present",
    "phi_pii_absent",
    "demographic_representation_addressed",
    "potential_misuse_acknowledged",
)


class ChecklistItem(BaseModel):
    """One item in the ethics checklist.

    ``answer=True`` means compliant. ``answer=False`` is non-compliant; if
    ``waiver`` is ``None`` the item is a blocker, otherwise the waiver text
    explains why non-compliance is acceptable in this context.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Item name (snake_case, must be one of STANDARD_ITEMS)")
    answer: bool = Field(description="True = compliant; False = non-compliant")
    justification: str = Field(
        min_length=20,
        description="Explanation citing specific evidence (min 20 chars)",
    )
    waiver: str | None = Field(
        default=None,
        description=(
            "If answer=False: explicit waiver string (non-compliance is acceptable) " "or None (item blocks delivery)."
        ),
    )


class EthicsChecklist(BaseModel):
    """Full ethics review output: 12 standard items + overall verdict."""

    model_config = ConfigDict(frozen=True)

    items: list[ChecklistItem] = Field(
        description="Exactly 12 items, in canonical STANDARD_ITEMS order",
    )
    overall_verdict: Literal["pass", "pass_with_waivers", "block"] = Field(
        description=(
            "'pass' = all items compliant; 'pass_with_waivers' = some items "
            "non-compliant but waived; 'block' = at least one non-compliant item "
            "without a waiver."
        ),
    )
    blocker_items: list[str] = Field(
        default_factory=list,
        description="Names of items where answer=False AND waiver=None",
    )
