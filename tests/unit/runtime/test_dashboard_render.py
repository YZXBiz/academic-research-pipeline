"""Tests for the events-driven dashboard renderer."""

from __future__ import annotations

import json
import logging
from functools import reduce
from typing import TYPE_CHECKING

from rich.console import Console

from academic_pipeline.runtime.dashboard import (
    RunState,
    apply_event,
    derive_state,
    read_events,
    render,
)


if TYPE_CHECKING:
    from pathlib import Path


def _render_to_text(state: RunState) -> str:
    """Render the panel and capture as plain text."""
    console = Console(width=120, record=True)
    console.print(render(state))
    return console.export_text()


def test_run_state_empty_returns_pending_state() -> None:
    state = RunState.empty()
    assert state.run_id == ""
    assert state.topic == ""
    assert state.started_at is None
    assert state.resumed_count == 0
    assert state.pipeline_status == "pending"
    assert state.pipeline_error is None
    assert state.current_stage is None
    assert dict(state.stages) == {}


def test_read_events_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert read_events(tmp_path / "no.jsonl") == []


def test_read_events_skips_malformed_tail(tmp_path: Path, caplog) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps({"ts": 1.0, "type": "a"}) + "\n"
        + json.dumps({"ts": 2.0, "type": "b"}) + "\n"
        + json.dumps({"ts": 3.0, "type": "c"}) + "\n"
        + '{"ts": 4.0, "type": "d"'
    )
    with caplog.at_level(logging.WARNING):
        events = read_events(p)
    assert [e["type"] for e in events] == ["a", "b", "c"]


def test_read_events_skips_malformed_middle_line(tmp_path: Path, caplog) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps({"ts": 1.0, "type": "a"}) + "\n"
        + "this is not json\n"
        + json.dumps({"ts": 3.0, "type": "c"}) + "\n"
    )
    with caplog.at_level(logging.WARNING):
        events = read_events(p)
    assert [e["type"] for e in events] == ["a", "c"]


def test_apply_event_pipeline_start_sets_metadata() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start",
        "run_id": "r1", "topic": "T", "resumed": False,
    })
    assert state.run_id == "r1"
    assert state.topic == "T"
    assert state.started_at == 100.0
    assert state.resumed_count == 0
    assert state.pipeline_status == "running"


def test_apply_event_second_pipeline_start_increments_resumed_count() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    state = apply_event(state, {
        "ts": 200.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": True,
    })
    assert state.resumed_count == 1
    assert state.started_at == 100.0
    assert state.pipeline_status == "running"


def test_apply_event_unknown_type_returns_state_unchanged() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    after = apply_event(state, {"ts": 999.0, "type": "future_event_type", "data": "x"})
    assert after == state


def test_apply_event_is_immutable() -> None:
    state = RunState.empty()
    new = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    assert state.run_id == ""
    assert new is not state


def test_apply_event_stage_change_first_stage_creates_running_record() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    state = apply_event(state, {
        "ts": 110.0, "type": "stage_change", "stage": "research", "previous": None,
    })
    assert state.current_stage == "research"
    assert state.stages["research"].status == "running"
    assert state.stages["research"].started_at == 110.0
    assert state.stages["research"].ended_at is None


def test_apply_event_stage_change_marks_previous_completed() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    state = apply_event(state, {
        "ts": 110.0, "type": "stage_change", "stage": "research", "previous": None,
    })
    state = apply_event(state, {
        "ts": 200.0, "type": "stage_change", "stage": "experiment", "previous": "research",
    })
    assert state.current_stage == "experiment"
    assert state.stages["research"].status == "completed"
    assert state.stages["research"].ended_at == 200.0
    assert state.stages["experiment"].status == "running"
    assert state.stages["experiment"].started_at == 200.0


def test_apply_event_node_complete_appends_to_stage() -> None:
    state = RunState.empty()
    for ev in [
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "research", "previous": None},
        {
            "ts": 120.0, "type": "node_complete", "stage": "research",
            "node": "RQClarifierNode", "scope": "subgraph", "duration_s": 5.0,
        },
        {
            "ts": 130.0, "type": "node_complete", "stage": "research",
            "node": "BibliographyBuilderNode", "scope": "subgraph", "duration_s": 8.0,
        },
    ]:
        state = apply_event(state, ev)
    nodes = state.stages["research"].nodes
    assert [n.name for n in nodes] == ["RQClarifierNode", "BibliographyBuilderNode"]
    assert nodes[0].duration_s == 5.0
    assert nodes[0].status == "completed"
    assert nodes[0].scope == "subgraph"


def test_apply_event_node_complete_creates_stage_if_missing() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False,
    })
    state = apply_event(state, {
        "ts": 200.0, "type": "node_complete", "stage": "research",
        "node": "X", "scope": "outer", "duration_s": 1.0,
    })
    assert "research" in state.stages
    assert state.stages["research"].started_at == 200.0
    assert state.stages["research"].nodes[0].name == "X"


def test_apply_event_node_error_marks_stage_error() -> None:
    state = RunState.empty()
    for ev in [
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "experiment", "previous": None},
        {
            "ts": 120.0, "type": "node_error", "stage": "experiment",
            "node": "DesignNode", "scope": "subgraph", "error": "boom",
        },
    ]:
        state = apply_event(state, ev)
    assert state.stages["experiment"].status == "error"
    node = state.stages["experiment"].nodes[0]
    assert node.status == "error"
    assert node.error == "boom"


def test_apply_event_pipeline_complete_marks_current_stage_completed() -> None:
    state = RunState.empty()
    for ev in [
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "summary", "previous": None},
        {"ts": 200.0, "type": "pipeline_complete"},
    ]:
        state = apply_event(state, ev)
    assert state.pipeline_status == "completed"
    assert state.stages["summary"].status == "completed"
    assert state.stages["summary"].ended_at == 200.0


def test_apply_event_pipeline_error_records_error() -> None:
    state = RunState.empty()
    for ev in [
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 200.0, "type": "pipeline_error", "error": "kaboom"},
    ]:
        state = apply_event(state, ev)
    assert state.pipeline_status == "error"
    assert state.pipeline_error == "kaboom"


def test_derive_state_equals_iterative_apply() -> None:
    events = [
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "research", "previous": None},
        {
            "ts": 120.0, "type": "node_complete", "stage": "research",
            "node": "X", "scope": "subgraph", "duration_s": 1.0,
        },
        {"ts": 200.0, "type": "stage_change", "stage": "write", "previous": "research"},
        {"ts": 300.0, "type": "pipeline_complete"},
    ]
    derived = derive_state(events)
    expected = reduce(apply_event, events, RunState.empty())
    assert derived == expected
    assert derived.pipeline_status == "completed"


def test_derive_state_empty_events_returns_empty_state() -> None:
    assert derive_state([]) == RunState.empty()


def test_render_includes_topic_and_status() -> None:
    state = derive_state([
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "Quantum widgets", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "research", "previous": None},
    ])
    text = _render_to_text(state)
    assert "Quantum widgets" in text
    assert "RUNNING" in text.upper()
    assert "r1" in text


def test_render_orders_stages_by_display_order() -> None:
    state = derive_state([
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 110.0, "type": "stage_change", "stage": "summary", "previous": None},
        {"ts": 120.0, "type": "stage_change", "stage": "research", "previous": "summary"},
    ])
    text = _render_to_text(state)
    research_pos = text.lower().index("research")
    summary_pos = text.lower().index("summary")
    assert research_pos < summary_pos


def test_render_handles_empty_state() -> None:
    text = _render_to_text(RunState.empty())
    assert text
    assert "pending" in text.lower() or "no events" in text.lower()


def test_render_shows_pipeline_error_when_status_is_error() -> None:
    state = derive_state([
        {"ts": 100.0, "type": "pipeline_start", "run_id": "r1", "topic": "T", "resumed": False},
        {"ts": 200.0, "type": "pipeline_error", "error": "It broke spectacularly"},
    ])
    text = _render_to_text(state)
    assert "It broke spectacularly" in text
    assert "ERROR" in text.upper()


from academic_pipeline.runtime.dashboard import latest_run_dir


def test_latest_run_dir_returns_none_when_symlink_missing(tmp_path: Path) -> None:
    assert latest_run_dir(tmp_path) is None


def test_latest_run_dir_resolves_symlink(tmp_path: Path) -> None:
    target = tmp_path / "run-0501-1530_a1b2"
    target.mkdir()
    (tmp_path / "latest").symlink_to("run-0501-1530_a1b2")
    assert latest_run_dir(tmp_path) == target


def test_apply_event_watchdog_killing_appended_to_actions() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "watchdog_killing", "scope": "watchdog",
        "pgid": 42, "age_s": 90.5, "strike": 1,
    })
    assert len(state.watchdog_actions) == 1
    assert state.watchdog_actions[0].action == "killing"
    assert state.watchdog_actions[0].pgid == 42
    assert state.watchdog_actions[0].age_s == 90.5
    assert state.watchdog_actions[0].strike == 1


def test_apply_event_watchdog_killed_records_killed_cleanly() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 110.0, "type": "watchdog_killed", "scope": "watchdog",
        "killed_cleanly": True,
    })
    assert state.watchdog_actions[0].action == "killed"
    assert state.watchdog_actions[0].killed_cleanly is True


def test_apply_event_watchdog_resuming_and_resumed_appended() -> None:
    state = RunState.empty()
    state = apply_event(state, {"ts": 120.0, "type": "watchdog_resuming", "scope": "watchdog"})
    state = apply_event(state, {"ts": 121.0, "type": "watchdog_resumed", "scope": "watchdog"})
    actions = [wa.action for wa in state.watchdog_actions]
    assert actions == ["resuming", "resumed"]


def test_apply_event_watchdog_aborted_sets_pipeline_status_and_error() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 200.0, "type": "watchdog_aborted", "scope": "watchdog",
        "reason": "3 consecutive recoveries with no progress", "strikes": 3,
    })
    assert state.pipeline_status == "watchdog_aborted"
    assert state.pipeline_error == "3 consecutive recoveries with no progress"
    assert state.watchdog_actions[0].action == "aborted"
    assert state.watchdog_actions[0].reason == "3 consecutive recoveries with no progress"


def test_apply_event_watchdog_events_are_immutable() -> None:
    state = RunState.empty()
    new = apply_event(state, {"ts": 100.0, "type": "watchdog_killing", "scope": "watchdog"})
    assert state is not new
    assert state.watchdog_actions == ()
    assert len(new.watchdog_actions) == 1


def test_render_includes_watchdog_panel_when_actions_present() -> None:
    state = RunState.empty()
    state = apply_event(state, {
        "ts": 100.0, "type": "watchdog_killing", "scope": "watchdog",
        "pgid": 42, "age_s": 90.5, "strike": 1,
    })
    state = apply_event(state, {
        "ts": 110.0, "type": "watchdog_killed", "scope": "watchdog",
        "killed_cleanly": True,
    })
    out = _render_to_text(state)
    assert "watchdog" in out.lower()
    assert "killing" in out
    assert "killed" in out
    assert "42" in out  # pgid
