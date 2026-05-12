"""Tests for the structured 12-item ethics checklist (Spec 8 of SCI roadmap)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from academic_pipeline.models.ethics import (
    STANDARD_ITEMS,
    ChecklistItem,
    EthicsChecklist,
)
from academic_pipeline.research.ethics_validator import validate_ethics_checklist


# ---------------------------------------------------------------------------
# STANDARD_ITEMS list completeness
# ---------------------------------------------------------------------------


def test_standard_items_has_exactly_twelve() -> None:
    assert len(STANDARD_ITEMS) == 12


def test_standard_items_contains_required_names() -> None:
    expected = {
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
    }
    assert set(STANDARD_ITEMS) == expected


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------


def _make_item(name: str, *, answer: bool = True, waiver: str | None = None) -> ChecklistItem:
    return ChecklistItem(
        name=name,
        answer=answer,
        justification="A sufficiently long justification text for the item.",
        waiver=waiver,
    )


def _all_pass_items() -> list[ChecklistItem]:
    return [_make_item(name) for name in STANDARD_ITEMS]


def test_checklist_item_requires_min_20_char_justification() -> None:
    with pytest.raises(ValidationError):
        ChecklistItem(name="x", answer=True, justification="too short", waiver=None)


def test_checklist_item_accepts_valid_justification() -> None:
    item = _make_item("ai_assistance_disclosed")
    assert item.answer is True
    assert item.waiver is None


def test_ethics_checklist_construction() -> None:
    checklist = EthicsChecklist(
        items=_all_pass_items(),
        overall_verdict="pass",
        blocker_items=[],
    )
    assert len(checklist.items) == 12
    assert checklist.overall_verdict == "pass"


def test_ethics_checklist_is_frozen() -> None:
    checklist = EthicsChecklist(
        items=_all_pass_items(),
        overall_verdict="pass",
        blocker_items=[],
    )
    with pytest.raises(ValidationError):
        checklist.overall_verdict = "block"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validator: happy paths
# ---------------------------------------------------------------------------


def test_validator_accepts_all_pass() -> None:
    checklist = EthicsChecklist(
        items=_all_pass_items(),
        overall_verdict="pass",
        blocker_items=[],
    )
    out = validate_ethics_checklist(checklist)
    assert out is checklist


def test_validator_accepts_pass_with_waivers() -> None:
    items = _all_pass_items()
    items[1] = _make_item(
        "irb_approval_documented",
        answer=False,
        waiver="not applicable: paper uses only public BRFSS data, no human-subjects intervention",
    )
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass_with_waivers",
        blocker_items=[],
    )
    out = validate_ethics_checklist(checklist)
    assert out is checklist


def test_validator_accepts_block() -> None:
    items = _all_pass_items()
    items[6] = _make_item("structural_coi_absent", answer=False, waiver=None)
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="block",
        blocker_items=["structural_coi_absent"],
    )
    out = validate_ethics_checklist(checklist)
    assert out is checklist


# ---------------------------------------------------------------------------
# Validator: failure modes (each raises ModelRetry)
# ---------------------------------------------------------------------------


def test_validator_rejects_wrong_item_count() -> None:
    items = _all_pass_items()[:11]  # missing one
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass",
        blocker_items=[],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_out_of_order_items() -> None:
    items = _all_pass_items()
    items[0], items[1] = items[1], items[0]
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass",
        blocker_items=[],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_missing_blocker_item() -> None:
    """answer=False without waiver MUST appear in blocker_items."""
    items = _all_pass_items()
    items[6] = _make_item("structural_coi_absent", answer=False, waiver=None)
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="block",
        blocker_items=[],  # forgotten the blocker
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_waiver_in_blocker_items() -> None:
    """answer=False WITH waiver must NOT appear in blocker_items."""
    items = _all_pass_items()
    items[1] = _make_item(
        "irb_approval_documented",
        answer=False,
        waiver="not applicable: paper uses only public BRFSS data",
    )
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass_with_waivers",
        blocker_items=["irb_approval_documented"],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_wrong_verdict_when_blocker_present() -> None:
    items = _all_pass_items()
    items[6] = _make_item("structural_coi_absent", answer=False, waiver=None)
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass_with_waivers",  # should be "block"
        blocker_items=["structural_coi_absent"],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_wrong_verdict_when_waiver_present() -> None:
    items = _all_pass_items()
    items[1] = _make_item(
        "irb_approval_documented",
        answer=False,
        waiver="not applicable: paper uses only public BRFSS data",
    )
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass",  # should be "pass_with_waivers"
        blocker_items=[],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_wrong_verdict_when_all_pass() -> None:
    checklist = EthicsChecklist(
        items=_all_pass_items(),
        overall_verdict="block",  # should be "pass"
        blocker_items=[],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


def test_validator_rejects_unknown_item_name() -> None:
    items = _all_pass_items()
    items[0] = _make_item("not_a_real_standard_item")
    checklist = EthicsChecklist(
        items=items,
        overall_verdict="pass",
        blocker_items=[],
    )
    with pytest.raises(ModelRetry):
        validate_ethics_checklist(checklist)


# ---------------------------------------------------------------------------
# PRD §6.1.T6: _ETHICS_VERDICT_MAP and EthicsReviewNode are deleted from
# research/graph.py. The 12-item ethics checklist now runs in the integrity
# subgraph (`EthicsChecklistNode` per §6.5.T1). The verdict mapping is no
# longer needed because integrity stores the full EthicsChecklist artifact
# rather than a derived Verdict enum.
# ---------------------------------------------------------------------------
