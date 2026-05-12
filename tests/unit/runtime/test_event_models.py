"""Tests for typed event models added in §6.8.T1.

PRD §18 documents the wire shapes for 5 new event types. These tests assert
that each is a frozen pydantic.BaseModel with the documented field set + type
constraints.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.runtime.events import (
    CascadeVerdictEvent,
    DoiGateFailureEvent,
    EthicsChecklistResultEvent,
    NoveltyGateVerdictEvent,
    NoveltyNeighbor,
    RecoveryEvent,
)


def test_recovery_event_accepts_documented_shape() -> None:
    evt = RecoveryEvent(
        layer=4,
        action="kill",
        reason="events_jsonl stale 612s ≥ 600s",
        strike=1,
        error_code="REC004",
    )
    assert evt.layer == 4
    assert evt.action == "kill"
    assert evt.strike == 1
    assert evt.error_code == "REC004"


def test_recovery_event_layer_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        RecoveryEvent(layer=5, action="kill", reason="r", strike=1, error_code="REC001")
    with pytest.raises(ValidationError):
        RecoveryEvent(layer=0, action="kill", reason="r", strike=1, error_code="REC001")


def test_recovery_event_action_is_literal() -> None:
    with pytest.raises(ValidationError):
        RecoveryEvent(layer=4, action="bogus", reason="r", strike=1, error_code="REC001")  # type: ignore[arg-type]


def test_recovery_event_strike_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        RecoveryEvent(layer=4, action="kill", reason="r", strike=0, error_code="REC001")
    with pytest.raises(ValidationError):
        RecoveryEvent(layer=4, action="kill", reason="r", strike=4, error_code="REC001")


def test_recovery_event_is_frozen() -> None:
    evt = RecoveryEvent(layer=1, action="resume", reason="r", strike=1, error_code="REC001")
    with pytest.raises(ValidationError):
        evt.layer = 2  # type: ignore[misc]


def test_doi_gate_failure_accepts_documented_shape() -> None:
    evt = DoiGateFailureEvent(
        doi="10.1234/example.bad",
        crossref_status=404,
        blocking=True,
        error_code="REN001",
    )
    assert evt.doi == "10.1234/example.bad"
    assert evt.crossref_status == 404
    assert evt.blocking is True


def test_doi_gate_failure_is_frozen() -> None:
    evt = DoiGateFailureEvent(doi="10.1/x", crossref_status=200, blocking=False, error_code="REN001")
    with pytest.raises(ValidationError):
        evt.blocking = True  # type: ignore[misc]


def test_cascade_verdict_pass_omits_error_code() -> None:
    evt = CascadeVerdictEvent(
        stage="A",
        verdict="pass",
        score=0.91,
        reason="all gates green",
        short_circuited=False,
    )
    assert evt.error_code is None
    dumped = evt.model_dump(exclude_none=True)
    assert "error_code" not in dumped


def test_cascade_verdict_fail_carries_error_code() -> None:
    evt = CascadeVerdictEvent(
        stage="B",
        verdict="fail",
        score=0.42,
        reason="3 numeric claims lack trace tokens",
        short_circuited=True,
        error_code="CAS001",
    )
    assert evt.error_code == "CAS001"


def test_cascade_verdict_stage_is_literal() -> None:
    with pytest.raises(ValidationError):
        CascadeVerdictEvent(stage="D", verdict="pass", score=1.0, reason="r", short_circuited=False)  # type: ignore[arg-type]


def test_cascade_verdict_verdict_is_literal() -> None:
    with pytest.raises(ValidationError):
        CascadeVerdictEvent(stage="A", verdict="maybe", score=1.0, reason="r", short_circuited=False)  # type: ignore[arg-type]


def test_novelty_gate_verdict_novel_omits_error_code() -> None:
    evt = NoveltyGateVerdictEvent(
        verdict="novel",
        max_similarity=0.42,
        tau_warn=0.78,
        tau_block=0.92,
        neighbors=[],
    )
    assert evt.error_code is None
    assert evt.differentiation_paragraph is None


def test_novelty_gate_verdict_partial_carries_diff_paragraph() -> None:
    neighbor = NoveltyNeighbor(
        title="Prior work on X",
        doi="10.1/abc",
        semantic_scholar_id="abc123",
        cosine_similarity=0.83,
        abstract_excerpt="first 200 chars...",
    )
    evt = NoveltyGateVerdictEvent(
        verdict="partial",
        max_similarity=0.83,
        tau_warn=0.78,
        tau_block=0.92,
        neighbors=[neighbor],
        differentiation_paragraph="Our work differs because...",
        error_code="NOV003",
    )
    assert evt.differentiation_paragraph == "Our work differs because..."
    assert evt.error_code == "NOV003"
    assert evt.neighbors[0].cosine_similarity == 0.83


def test_novelty_gate_verdict_verdict_is_literal() -> None:
    with pytest.raises(ValidationError):
        NoveltyGateVerdictEvent(
            verdict="bogus",  # type: ignore[arg-type]
            max_similarity=0.5,
            tau_warn=0.78,
            tau_block=0.92,
            neighbors=[],
        )


def test_ethics_checklist_pass_omits_error_code() -> None:
    evt = EthicsChecklistResultEvent(
        items_total=12,
        items_pass=12,
        items_fail=0,
        items_na=0,
        fails=[],
        blocking=False,
    )
    assert evt.error_code is None


def test_ethics_checklist_fail_carries_error_code() -> None:
    evt = EthicsChecklistResultEvent(
        items_total=12,
        items_pass=10,
        items_fail=1,
        items_na=1,
        fails=[{"item": "data_provenance_disclosed", "reason": "missing source"}],
        blocking=True,
        error_code="ETH004",
    )
    assert evt.items_fail == 1
    assert evt.error_code == "ETH004"
    assert evt.fails[0]["item"] == "data_provenance_disclosed"


def test_ethics_checklist_counts_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        EthicsChecklistResultEvent(
            items_total=-1,
            items_pass=0,
            items_fail=0,
            items_na=0,
            fails=[],
            blocking=False,
        )
