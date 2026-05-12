"""End-to-end smoke for the hang recovery system.

Spawns a fake "pipeline" subprocess that:
  1. writes a pipeline_start event to events.jsonl
  2. writes a heartbeat.txt + .pid + .pgid file
  3. then sleeps forever (simulates a hang)

Then runs the watchdog against it with a tight max_idle. Asserts the
watchdog detects the stall, kills the process group, and emits the
expected watchdog_killing/watchdog_killed events.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path


_FAKE_PIPELINE_SCRIPT = """
import json, os, signal, sys, time
from pathlib import Path

thread_id = sys.argv[1]
output_dir = Path(sys.argv[2])
persistence_dir = Path(sys.argv[3])

run_dir = output_dir / thread_id
run_dir.mkdir(parents=True, exist_ok=True)

# Write pipeline_start event
events_path = run_dir / "events.jsonl"
event = {
    "ts": time.time(),
    "type": "pipeline_start",
    "run_id": thread_id,
    "topic": "fake",
    "resumed": False,
}
events_path.write_text(json.dumps(event) + "\\n")

# Write PID/PGID files (own process group via setsid was set by parent)
persistence_dir.mkdir(parents=True, exist_ok=True)
(persistence_dir / f"{thread_id}.pid").write_text(str(os.getpid()))
(persistence_dir / f"{thread_id}.pgid").write_text(str(os.getpgid(0)))

# Write heartbeat once, then go silent (simulates a hang AFTER first beat)
heartbeat_path = run_dir / "heartbeat.txt"
heartbeat_path.write_text(str(time.time()))

# Now sleep forever (simulating a wedged process)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
time.sleep(3600)
"""


def test_watchdog_kills_stalled_pipeline_end_to_end(tmp_path: Path) -> None:
    """Spawn fake pipeline; run watchdog; assert kill happens within max_idle."""
    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    persistence_dir.mkdir()
    output_dir.mkdir()

    script_path = tmp_path / "fake_pipeline.py"
    script_path.write_text(_FAKE_PIPELINE_SCRIPT)

    thread_id = "run-e2e-test"
    pipeline_proc = subprocess.Popen(
        [sys.executable, str(script_path), thread_id, str(output_dir), str(persistence_dir)],
        preexec_fn=os.setsid,
    )

    # Wait for fake pipeline to write its initial files
    for _ in range(60):
        if (persistence_dir / f"{thread_id}.pgid").exists():
            break
        time.sleep(0.2)
    else:
        pipeline_proc.kill()
        raise AssertionError("fake pipeline did not write pgid file")

    # Run watchdog with tight thresholds, no auto-resume (one-shot mode)
    watchdog_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "academic_pipeline",
            "watchdog",
            thread_id,
            "--max-idle",
            "3",
            "--poll",
            "1",
            "--output-dir",
            str(output_dir),
            "--persistence-dir",
            str(persistence_dir),
        ],
        preexec_fn=os.setsid,
    )

    # Watchdog should kill the fake pipeline within ~10 seconds (max_idle=3 + poll=1 + grace=5)
    try:
        watchdog_proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        watchdog_proc.kill()
        pipeline_proc.kill()
        raise AssertionError("watchdog did not finish within 30s") from None

    # Fake pipeline should be dead by now
    pipeline_proc.wait(timeout=5)
    assert pipeline_proc.returncode is not None

    # events.jsonl should now contain watchdog_killing + watchdog_killed
    events_path = output_dir / thread_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "watchdog_killing" in types
    assert "watchdog_killed" in types


def test_watchdog_auto_resume_unlinks_stale_pgid_then_invokes_resume(tmp_path: Path) -> None:
    """End-to-end: with --auto-resume, watchdog unlinks stale pgid and Popens make resume.

    We patch the actual `make resume` step out (don't want to invoke the real
    pipeline in this test) but verify the unlink + Popen call sequence.
    """
    import os as _os

    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    (output_dir / "test-resume").mkdir(parents=True)
    persistence_dir.mkdir()

    events_path = output_dir / "test-resume" / "events.jsonl"
    events_path.write_text('{"ts": 1.0, "type": "pipeline_start", "run_id": "test-resume"}\n')
    ancient = time.time() - 3600
    _os.utime(events_path, (ancient, ancient))

    pgid_path = persistence_dir / "test-resume.pgid"
    pgid_path.write_text("999999")  # stale dead pgid

    # Patch _kill_pgid (no real kill), Popen (don't actually start make resume),
    # and shorten resume PID timeout so test finishes fast
    from unittest.mock import MagicMock, patch

    popen_calls: list[list[str]] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        popen_calls.append(cmd)
        return MagicMock()

    with (
        patch("academic_pipeline.recovery.watchdog._kill_pgid", return_value=True),
        patch("academic_pipeline.recovery.watchdog.subprocess.Popen", side_effect=_fake_popen),
        patch("academic_pipeline.recovery.watchdog._RESUME_PID_TIMEOUT_S", 1),
        # Suppress event emission so events.jsonl stays at one line and the
        # 3-strikes counter (max_strikes=1) trips on the second iteration.
        patch("academic_pipeline.recovery.watchdog._emit_watchdog_event"),
    ):
        from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

        rc = run_watchdog(
            WatchdogConfig(
                thread_id="test-resume",
                max_idle_s=1,
                poll_interval_s=1,
                output_dir=output_dir,
                persistence_dir=persistence_dir,
                auto_resume=True,
                max_strikes=1,
            )
        )

    assert rc == 2  # 3-strikes abort (max_strikes=1)
    # The supervised-resume command was attempted (NOT bare `resume`, NOT `make`)
    # — this is the post-fix-#4 behavior: resumed pipeline gets its own watchdog.
    assert any("supervised-resume" in cmd for cmd in popen_calls)
    # And it must NOT route through `make` (the watchdog now invokes Python module directly)
    assert all("make" not in cmd for cmd in popen_calls)


# PRD §6.6.T4 — three integration tests for hang recovery e2e.


def test_max_recoveries_flag_via_cli_is_accepted_and_kill_path_runs(tmp_path: Path) -> None:
    """`--max-recoveries N` (PRD §6.6.T1) is accepted at the CLI and the kill path runs.

    End-to-end: spawn the fake-pipeline harness (mirroring
    test_watchdog_kills_stalled_pipeline_end_to_end), invoke the watchdog
    subprocess with `--max-recoveries 5`, and verify the watchdog kills the
    stalled pipeline AND emits a `watchdog_killing` event tagged with a
    `strike` field. The strike-tracking is what gates the abort threshold —
    its presence proves the flag reached the runtime path.

    The unit test in tests/unit/cli/test_watchdog_command.py separately proves
    the flag value populates WatchdogConfig.max_strikes; together they give
    end-to-end coverage without invoking the 60s+ supervised-resume path.
    """
    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    persistence_dir.mkdir()
    output_dir.mkdir()

    script_path = tmp_path / "fake_pipeline.py"
    script_path.write_text(_FAKE_PIPELINE_SCRIPT)

    thread_id = "run-cli-max-recoveries"
    pipeline_proc = subprocess.Popen(
        [sys.executable, str(script_path), thread_id, str(output_dir), str(persistence_dir)],
        preexec_fn=os.setsid,
    )

    for _ in range(60):
        if (persistence_dir / f"{thread_id}.pgid").exists():
            break
        time.sleep(0.2)
    else:
        pipeline_proc.kill()
        raise AssertionError("fake pipeline did not write pgid file")

    watchdog_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "academic_pipeline",
            "watchdog",
            thread_id,
            "--max-idle",
            "3",
            "--poll",
            "1",
            "--output-dir",
            str(output_dir),
            "--persistence-dir",
            str(persistence_dir),
            "--max-recoveries",
            "5",  # the new canonical flag from §6.6.T1
        ],
        preexec_fn=os.setsid,
    )

    try:
        watchdog_proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        watchdog_proc.kill()
        pipeline_proc.kill()
        raise AssertionError("watchdog did not finish within 30s") from None

    pipeline_proc.wait(timeout=5)

    events_path = output_dir / thread_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "watchdog_killing" in types, f"expected watchdog_killing event, got {types}"
    killing = next(e for e in events if e["type"] == "watchdog_killing")
    # The strike field is what the abort threshold compares against; its
    # presence proves --max-recoveries reached the runtime gate.
    assert "strike" in killing, f"watchdog_killing missing 'strike' field: {killing}"
    assert isinstance(killing["strike"], int)


@pytest.mark.skip(reason="awaits 6.6.T2 in Phase 2 — generic recovery_event type not yet emitted")
def test_recovery_event_lines_present_after_forced_kill(tmp_path: Path) -> None:
    """After a forced kill, events.jsonl should contain a `recovery_event` record.

    Per PRD §6.6.T2, the new generic `recovery_event` shape ({layer, action,
    reason, strike, error_code: "REC###"}) covers L1-L3 alongside the existing
    5 watchdog_* event types (kept for backward compat with Logfire saved
    searches per AP18). This test will activate once §6.6.T2 lands in Phase 2.
    """
    raise NotImplementedError("waiting on §6.6.T2")


def test_dashboard_renders_recovery_count_from_watchdog_events() -> None:
    """`render(state)` after watchdog_killing/_killed events shows the action table.

    Replays a synthetic events.jsonl through derive_state, then renders to
    text. The watchdog action table must list both kills and the strike count;
    this is the on-screen "recovery count" surface.
    """
    from rich.console import Console

    from academic_pipeline.runtime.dashboard import RunState, apply_event, derive_state, render

    events: list[dict[str, object]] = [
        {"ts": 1.0, "type": "pipeline_start", "run_id": "test-rcount", "topic": "x", "resumed": False},
        {"ts": 2.0, "type": "watchdog_killing", "strike": 1, "age_s": 700, "pgid": 12345, "reason": "stall"},
        {"ts": 3.0, "type": "watchdog_killed", "strike": 1, "killed_cleanly": True},
        {"ts": 4.0, "type": "watchdog_killing", "strike": 2, "age_s": 700, "pgid": 12346, "reason": "stall again"},
        {"ts": 5.0, "type": "watchdog_killed", "strike": 2, "killed_cleanly": True},
    ]
    state = derive_state(events)
    assert len(state.watchdog_actions) == 4  # 2 killing + 2 killed
    kill_actions = [a for a in state.watchdog_actions if a.action == "killing"]
    assert len(kill_actions) == 2  # the recovery count
    assert {a.strike for a in kill_actions} == {1, 2}

    # Rendered output must surface the watchdog table title + at least one strike row.
    console = Console(width=120, record=True)
    console.print(render(state))
    rendered = console.export_text()
    assert "watchdog" in rendered.lower()
    assert "killing" in rendered

    # Sanity: the in-memory replay matches a cold derive_state walk (event log
    # is the authoritative source, dashboard is a pure function over it).
    cold = RunState.empty()
    for e in events:
        cold = apply_event(cold, e)
    assert cold == state
