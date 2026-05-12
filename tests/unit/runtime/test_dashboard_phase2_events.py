"""Tests for dashboard handling of the 5 new event types added in §6.8.T1.

Covers `apply_event` accumulation and `render` surfacing for:
- recovery_event
- doi_gate_failure
- cascade_verdict
- novelty_gate_verdict
- ethics_checklist_result

PRD §6.8.T2 + §6.8 target state.
"""

from __future__ import annotations

from rich.console import Console

from academic_pipeline.runtime.dashboard import (
    RunState,
    apply_event,
    render,
)


def _render(state: RunState) -> str:
    console = Console(width=140, record=True)
    console.print(render(state))
    return console.export_text()


# ---- apply_event accumulation ----------------------------------------------


def test_apply_event_recovery_event_increments_count() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "recovery_event",
            "layer": 4,
            "action": "kill",
            "reason": "stale 612s",
            "strike": 1,
            "error_code": "REC004",
        },
    )
    state = apply_event(
        state,
        {
            "ts": 2.0,
            "type": "recovery_event",
            "layer": 4,
            "action": "resume",
            "reason": "restarted",
            "strike": 1,
            "error_code": "REC005",
        },
    )
    assert len(state.recovery_events) == 2
    assert state.recovery_events[0].layer == 4
    assert state.recovery_events[1].action == "resume"


def test_apply_event_doi_gate_failure_accumulates() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "doi_gate_failure",
            "doi": "10.1/bad",
            "crossref_status": 404,
            "blocking": True,
            "error_code": "REN001",
        },
    )
    assert len(state.doi_gate_failures) == 1
    assert state.doi_gate_failures[0].doi == "10.1/bad"
    assert state.doi_gate_failures[0].blocking is True


def test_apply_event_cascade_verdict_accumulates_per_stage() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "cascade_verdict",
            "stage": "A",
            "verdict": "pass",
            "score": 0.91,
            "reason": "ok",
            "short_circuited": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 2.0,
            "type": "cascade_verdict",
            "stage": "B",
            "verdict": "fail",
            "score": 0.42,
            "reason": "trace tokens missing",
            "short_circuited": True,
            "error_code": "CAS001",
        },
    )
    assert len(state.cascade_verdicts) == 2
    assert state.cascade_verdicts[0].stage == "A"
    assert state.cascade_verdicts[1].verdict == "fail"


def test_apply_event_novelty_gate_verdict_records_score() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "novelty_gate_verdict",
            "verdict": "partial",
            "max_similarity": 0.83,
            "tau_warn": 0.78,
            "tau_block": 0.92,
            "neighbors": [],
            "differentiation_paragraph": "diff",
            "error_code": "NOV003",
        },
    )
    assert state.novelty_verdict is not None
    assert state.novelty_verdict.verdict == "partial"
    assert state.novelty_verdict.max_similarity == 0.83


def test_apply_event_ethics_checklist_result_records_summary() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "ethics_checklist_result",
            "items_total": 12,
            "items_pass": 10,
            "items_fail": 1,
            "items_na": 1,
            "fails": [{"item": "x", "reason": "y"}],
            "blocking": True,
            "error_code": "ETH004",
        },
    )
    assert state.ethics_checklist is not None
    assert state.ethics_checklist.items_pass == 10
    assert state.ethics_checklist.items_fail == 1


def test_apply_event_unknown_type_unchanged() -> None:
    state = RunState.empty()
    state = apply_event(state, {"ts": 1.0, "type": "totally_unknown_kind"})
    assert state.recovery_events == ()
    assert state.cascade_verdicts == ()


# ---- render surfacing ------------------------------------------------------


def test_render_surfaces_recovery_count_when_present() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "recovery_event",
            "layer": 4,
            "action": "kill",
            "reason": "stale 612s",
            "strike": 2,
            "error_code": "REC004",
        },
    )
    text = _render(state)
    assert "recovery" in text.lower()
    assert "REC004" in text or "stale 612s" in text


def test_render_surfaces_cascade_per_stage_when_present() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "cascade_verdict",
            "stage": "B",
            "verdict": "fail",
            "score": 0.42,
            "reason": "trace tokens missing",
            "short_circuited": True,
            "error_code": "CAS001",
        },
    )
    text = _render(state)
    assert "cascade" in text.lower()
    assert "B" in text
    assert "fail" in text.lower()


def test_render_surfaces_novelty_score_panel_when_present() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "novelty_gate_verdict",
            "verdict": "partial",
            "max_similarity": 0.83,
            "tau_warn": 0.78,
            "tau_block": 0.92,
            "neighbors": [],
        },
    )
    text = _render(state)
    assert "novelty" in text.lower()
    assert "0.83" in text
    assert "partial" in text.lower()


def test_render_surfaces_ethics_summary_when_present() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "ethics_checklist_result",
            "items_total": 12,
            "items_pass": 10,
            "items_fail": 1,
            "items_na": 1,
            "fails": [],
            "blocking": True,
        },
    )
    text = _render(state)
    assert "ethics" in text.lower()
    # pass / total figures surfaced
    assert "10" in text
    assert "12" in text


def test_render_surfaces_doi_gate_failure_when_blocking() -> None:
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "doi_gate_failure",
            "doi": "10.1/bad",
            "crossref_status": 404,
            "blocking": True,
            "error_code": "REN001",
        },
    )
    text = _render(state)
    assert "doi" in text.lower()
    assert "10.1/bad" in text


def test_render_omits_phase2_panels_when_no_phase2_events() -> None:
    """Render must stay quiet when no new event types have fired (back-compat)."""
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    text = _render(state).lower()
    # Stage table contains "review" (a stage name) but ethics/cascade/novelty
    # panels should not appear when no events have fired.
    assert "ethics checklist" not in text
    assert "cascade verdicts" not in text
    assert "novelty gate" not in text


def test_render_back_compat_existing_pipeline_with_no_new_events() -> None:
    """Existing render path must still work end-to-end without phase 2 events."""
    state = RunState.empty()
    state = apply_event(
        state,
        {
            "ts": 0.0,
            "type": "pipeline_start",
            "run_id": "r1",
            "topic": "topic",
            "resumed": False,
        },
    )
    state = apply_event(
        state,
        {
            "ts": 1.0,
            "type": "stage_change",
            "stage": "research",
        },
    )
    state = apply_event(
        state,
        {
            "ts": 2.0,
            "type": "node_complete",
            "stage": "research",
            "node": "IntakeNode",
            "scope": "outer",
            "duration_s": 1.5,
        },
    )
    text = _render(state)
    assert "ACADEMIC PIPELINE" in text
    assert "research" in text
    assert "IntakeNode" in text
