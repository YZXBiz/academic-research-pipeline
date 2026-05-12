"""Consolidated dashboard test suite per PRD §6.8.T6.

Four canonical tests covering the four named coverage areas from PRD §6.8.T6:

1. schema version mismatch rejection
2. new event types render
3. throttle debounce
4. recovery count surfaces

The underlying behaviors are also covered with depth in:
- test_schema_version.py (11 tests)
- test_dashboard_phase2_events.py (13 tests)
- test_dashboard_debounce.py (8 tests)
- test_dashboard_render.py (29 tests)

This file is the single canonical reference satisfying PRD §6.8.T6's
literal four-test contract; the deeper coverage stays in the focused
files.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from academic_pipeline.runtime.dashboard import (
    DashboardDebouncer,
    RunState,
    SchemaVersionMismatch,
    apply_event,
    render,
    validate_schema_version,
)


if TYPE_CHECKING:
    from pathlib import Path


def _render(state: RunState) -> str:
    console = Console(width=140, record=True)
    console.print(render(state))
    return console.export_text()


def test_schema_version_mismatch_rejection(tmp_path: Path) -> None:
    """PRD §6.8.T3 — renderer rejects events.jsonl whose schema major differs."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"event_type": "schema_version", "version": "3.0.0"}) + "\n")
    with pytest.raises(SchemaVersionMismatch) as exc_info:
        validate_schema_version(events_path)
    assert "DSH001" in str(exc_info.value)


def test_new_event_types_render() -> None:
    """PRD §6.8.T1+T2 — the 5 new event types accumulate and render."""
    state = RunState.empty()
    state = apply_event(
        state,
        {"ts": 0.0, "type": "pipeline_start", "run_id": "r", "topic": "t", "resumed": False},
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
    state = apply_event(
        state,
        {
            "ts": 2.0,
            "type": "novelty_gate_verdict",
            "verdict": "partial",
            "max_similarity": 0.83,
            "tau_warn": 0.78,
            "tau_block": 0.92,
            "neighbors": [],
        },
    )
    state = apply_event(
        state,
        {
            "ts": 3.0,
            "type": "ethics_checklist_result",
            "items_total": 12,
            "items_pass": 10,
            "items_fail": 1,
            "items_na": 1,
            "fails": [],
            "blocking": True,
        },
    )
    text = _render(state).lower()
    assert "cascade" in text
    assert "novelty" in text
    assert "ethics" in text


def test_throttle_debounce_caps_at_4hz() -> None:
    """PRD §6.8.T4 — DashboardDebouncer caps writes at 4 Hz (250ms interval)."""
    deb = DashboardDebouncer(min_interval_s=0.25)
    assert deb.acquire(now=100.0) is True  # first call always allowed
    assert deb.acquire(now=100.10) is False  # within 250ms
    assert deb.acquire(now=100.25) is True  # boundary inclusive


def test_recovery_count_surfaces() -> None:
    """PRD §6.8.T2 — recovery_event records show up in the rendered dashboard."""
    state = RunState.empty()
    state = apply_event(
        state,
        {"ts": 0.0, "type": "pipeline_start", "run_id": "r", "topic": "t", "resumed": False},
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
    state = apply_event(
        state,
        {
            "ts": 2.0,
            "type": "recovery_event",
            "layer": 4,
            "action": "resume",
            "reason": "restarted",
            "strike": 2,
            "error_code": "REC005",
        },
    )
    text = _render(state).lower()
    assert "recovery" in text
    assert "count=2" in text
