"""Tests for the WatchdogConfig dataclass + watchdog helper functions."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from academic_pipeline.recovery.watchdog import (
    WatchdogConfig,
    _age,
    _kill_pgid,
    _read_int,
)


if TYPE_CHECKING:
    from pathlib import Path


def test_watchdog_config_is_frozen() -> None:
    """WatchdogConfig is frozen — assigning to a field must raise FrozenInstanceError."""
    import dataclasses

    import pytest

    cfg = WatchdogConfig(thread_id="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.thread_id = "other"  # type: ignore[misc]


def test_watchdog_config_defaults() -> None:
    cfg = WatchdogConfig(thread_id="t")
    # 600s (10min) gives headroom over the slowest known node
    # (SourceVerificationNode silent S2/CrossRef loops at ~60-120s) while
    # still recovering the multi-hour proxy-SSE wedges this watchdog
    # exists for. 75s was the original default and proved much too aggressive.
    assert cfg.max_idle_s == 600
    assert cfg.poll_interval_s == 30
    assert cfg.auto_resume is False
    assert cfg.max_strikes == 3


def test_age_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert _age(tmp_path / "no.txt") is None


def test_age_returns_seconds_since_mtime(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_text("x")
    age = _age(p)
    assert age is not None
    assert 0.0 <= age < 1.0


def test_read_int_returns_int(tmp_path: Path) -> None:
    p = tmp_path / "n"
    p.write_text("12345\n")
    assert _read_int(p) == 12345


def test_read_int_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert _read_int(tmp_path / "no") is None


def test_read_int_returns_none_for_garbage(tmp_path: Path) -> None:
    p = tmp_path / "g"
    p.write_text("not an int")
    assert _read_int(p) is None


def test_kill_pgid_returns_true_for_nonexistent_group() -> None:
    # PGID 999999 will not exist
    assert _kill_pgid(999999) is True


def test_kill_pgid_terminates_real_process() -> None:
    """Spawn a child process group, kill it via _kill_pgid, assert dead.

    Uses subprocess.Popen with preexec_fn=os.setsid so the new process group
    is established before the child starts running, avoiding the race
    inherent to multiprocessing.Process on spawn-default platforms (macOS).
    """
    import subprocess
    import sys

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        preexec_fn=os.setsid,
    )
    time.sleep(0.3)  # let it run
    pgid = os.getpgid(proc.pid)
    assert pgid == proc.pid, "child must be its own group leader"
    killed = _kill_pgid(pgid)
    rc = proc.wait(timeout=5)
    assert killed is True
    assert rc != 0  # killed by signal


def test_run_watchdog_unlinks_stale_pgid_before_resume(tmp_path: Path) -> None:
    """After SIGKILL bypasses ProcessLock cleanup, the watchdog must remove
    the stale pgid file before the polling loop, otherwise Popen'd resume
    appears to succeed instantly (reading a dead pgid).
    """
    from unittest.mock import patch

    from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    (output_dir / "test-id").mkdir(parents=True)
    persistence_dir.mkdir()

    # Simulate a stalled pipeline: events.jsonl with one event from the past
    events_path = output_dir / "test-id" / "events.jsonl"
    events_path.write_text('{"ts": 1.0, "type": "pipeline_start", "run_id": "test-id"}\n')
    # Force mtime to be ancient so watchdog detects stall on first poll
    import os as _os

    ancient = time.time() - 3600
    _os.utime(events_path, (ancient, ancient))

    # Stale pgid file (simulating the SIGKILLed pipeline's leftover lock)
    pgid_path = persistence_dir / "test-id.pgid"
    pgid_path.write_text("999999")  # pretend-dead pgid

    cfg = WatchdogConfig(
        thread_id="test-id",
        max_idle_s=1,
        poll_interval_s=1,
        output_dir=output_dir,
        persistence_dir=persistence_dir,
        auto_resume=True,
        max_strikes=1,  # abort after 1 strike to keep test fast
    )

    # Patch _kill_pgid (no real kill) and Popen (don't actually start make resume)
    # and verify pgid_path was unlinked between the kill and the Popen call
    pgid_existed_before_popen: dict[str, bool] = {}

    def _record_unlink_state(*args: object, **kwargs: object) -> object:
        from unittest.mock import MagicMock

        pgid_existed_before_popen["existed"] = pgid_path.exists()
        return MagicMock()

    with (
        patch("academic_pipeline.recovery.watchdog._kill_pgid", return_value=True),
        patch("academic_pipeline.recovery.watchdog.subprocess.Popen", side_effect=_record_unlink_state),
        patch("academic_pipeline.recovery.watchdog._RESUME_PID_TIMEOUT_S", 1),
        # Suppress event emission so events.jsonl mtime stays ancient and the
        # event count stays stable, letting max_strikes=1 trigger abort cleanly.
        patch("academic_pipeline.recovery.watchdog._emit_watchdog_event"),
    ):
        run_watchdog(cfg)

    assert pgid_existed_before_popen["existed"] is False, (
        "stale pgid file should have been unlinked before Popen so the new resume's pgid wins"
    )


def test_count_pipeline_events_excludes_watchdog_scope(tmp_path: "Path") -> None:
    """The strike counter must filter watchdog's own events.

    Regression: previously _count_lines counted ALL lines, so the watchdog's
    kill+resume cycle (which writes 3+ events itself) made event_count
    strictly increase between stalls — the 3-strikes safety net never tripped.
    """
    import json as _json

    from academic_pipeline.recovery.watchdog import _count_pipeline_events

    events_path = tmp_path / "events.jsonl"
    lines = [
        _json.dumps({"type": "pipeline_start", "scope": "outer"}),
        _json.dumps({"type": "node_complete", "scope": "outer", "node": "Intake"}),
        _json.dumps({"type": "watchdog_killing", "scope": "watchdog", "pgid": 123}),
        _json.dumps({"type": "watchdog_killed", "scope": "watchdog"}),
        _json.dumps({"type": "watchdog_resuming", "scope": "watchdog"}),
        _json.dumps({"type": "node_complete", "scope": "subgraph", "node": "Foo"}),
    ]
    events_path.write_text("\n".join(lines) + "\n")

    # 3 pipeline events; 3 watchdog events filtered out
    assert _count_pipeline_events(events_path) == 3


def test_count_pipeline_events_returns_zero_for_missing_file(tmp_path: "Path") -> None:
    from academic_pipeline.recovery.watchdog import _count_pipeline_events

    assert _count_pipeline_events(tmp_path / "missing.jsonl") == 0


def test_count_pipeline_events_treats_malformed_as_pipeline(tmp_path: "Path") -> None:
    """Conservative: malformed JSON lines count as pipeline events (not dropped)."""
    from academic_pipeline.recovery.watchdog import _count_pipeline_events

    events_path = tmp_path / "events.jsonl"
    events_path.write_text("garbage line\n{not json\n")
    assert _count_pipeline_events(events_path) == 2


def test_run_watchdog_3_strikes_fires_when_pipeline_makes_no_progress(tmp_path: "Path") -> None:
    """End-to-end: watchdog's own events must NOT keep resetting the strike counter.

    With the bug present, this test would loop forever because every kill cycle
    writes ≥3 watchdog events to events.jsonl, making event_count change between
    stalls, resetting strikes to 1 on every iteration. After the fix, only
    pipeline events count, so the counter actually reaches max_strikes.

    Notably, this test does NOT patch _emit_watchdog_event — that was the
    smoking gun in the original suite (it patched the function out to mask
    the bug). This test exercises the real emit path.
    """
    import json as _json
    from unittest.mock import MagicMock, patch

    from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    (output_dir / "test-strike").mkdir(parents=True)
    persistence_dir.mkdir()

    # Stale pipeline: one pipeline_start event, ancient mtime, fake pgid
    events_path = output_dir / "test-strike" / "events.jsonl"
    events_path.write_text(_json.dumps({
        "ts": 1.0, "type": "pipeline_start", "scope": "outer", "run_id": "test-strike",
    }) + "\n")
    ancient = time.time() - 3600
    os.utime(events_path, (ancient, ancient))

    pgid_path = persistence_dir / "test-strike.pgid"
    pgid_path.write_text("999999")  # dead pgid

    # Fake kill (no real process to kill) and Popen (don't actually invoke make resume)
    with (
        patch("academic_pipeline.recovery.watchdog._kill_pgid", return_value=True),
        patch("academic_pipeline.recovery.watchdog.subprocess.Popen", return_value=MagicMock()),
        patch("academic_pipeline.recovery.watchdog._RESUME_PID_TIMEOUT_S", 1),
    ):
        rc = run_watchdog(WatchdogConfig(
            thread_id="test-strike",
            max_idle_s=1,
            poll_interval_s=1,
            output_dir=output_dir,
            persistence_dir=persistence_dir,
            auto_resume=True,
            max_strikes=3,
        ))

    # Without the fix: would never abort (returns nothing, infinite loop hits test timeout)
    # With the fix: rc=2 from 3-strikes abort
    assert rc == 2

    # Verify watchdog DID emit its events to the same file (the fix isn't "stop emitting",
    # it's "stop counting watchdog events as progress")
    events = [_json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "watchdog_killing" in types
    assert "watchdog_aborted" in types


def test_watchdog_fires_when_events_stale_but_heartbeat_fresh(tmp_path: "Path") -> None:
    """Regression: heartbeat fresh + events.jsonl stale must still trigger.

    Failure mode from run-0504-1212_cf0d (1h41m unrecovered):
      - Pipeline hung in await on a dropped Anthropic SSE stream
      - heartbeat.txt daemon thread kept ticking every minute (process alive)
      - events.jsonl mtime was ancient (no real progress)
      - Watchdog used min(events_age, heart_age), so the fresh heartbeat
        masked the stale events file → watchdog never fired

    Fix: stall detection uses events.jsonl mtime ONLY. Heartbeat does not
    gate the staleness decision because the daemon thread keeps writing it
    even when the main async code is hung.

    Test simulates the daemon thread by repeatedly refreshing heartbeat.txt
    mtime via a sidecar thread for the duration of the run. Without the
    refresher the heartbeat ages out naturally and the buggy min() trips
    accidentally; with the refresher in place, only a watchdog that ignores
    heartbeat (the fixed behaviour) can detect the stall.
    """
    import json as _json
    import threading
    from unittest.mock import MagicMock, patch

    from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    (output_dir / "test-hb").mkdir(parents=True)
    persistence_dir.mkdir()

    # Stale events.jsonl (1 hour old) — proof-of-progress signal is dead
    events_path = output_dir / "test-hb" / "events.jsonl"
    events_path.write_text(_json.dumps({
        "ts": 1.0, "type": "pipeline_start", "scope": "outer", "run_id": "test-hb",
    }) + "\n")
    ancient = time.time() - 3600
    os.utime(events_path, (ancient, ancient))

    # Continuously-fresh heartbeat.txt simulating the daemon thread.
    # Without this, the heartbeat ages out within ~1s and the buggy code
    # fires accidentally — exactly the false-pass that masked the original
    # bug from earlier tests.
    heart_path = output_dir / "test-hb" / "heartbeat.txt"
    heart_path.write_text("alive")
    stop_refresher = threading.Event()

    def _refresh_heartbeat() -> None:
        while not stop_refresher.is_set():
            now = time.time()
            try:
                os.utime(heart_path, (now, now))
            except FileNotFoundError:
                pass
            time.sleep(0.1)

    refresher = threading.Thread(target=_refresh_heartbeat, daemon=True)
    refresher.start()

    pgid_path = persistence_dir / "test-hb.pgid"
    pgid_path.write_text("999999")

    try:
        with (
            patch("academic_pipeline.recovery.watchdog._kill_pgid", return_value=True),
            patch("academic_pipeline.recovery.watchdog.subprocess.Popen", return_value=MagicMock()),
            patch("academic_pipeline.recovery.watchdog._RESUME_PID_TIMEOUT_S", 1),
        ):
            rc = run_watchdog(WatchdogConfig(
                thread_id="test-hb",
                max_idle_s=1,
                poll_interval_s=1,
                output_dir=output_dir,
                persistence_dir=persistence_dir,
                auto_resume=True,
                max_strikes=3,
            ))
    finally:
        stop_refresher.set()
        refresher.join(timeout=1)

    # With the bug present: heartbeat refresher keeps min(ages) at ~0 forever,
    # watchdog never fires — pytest would have to externally time out.
    # With the fix: events.jsonl staleness alone trips the check, 3 strikes -> abort.
    assert rc == 2
    events = [_json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert "watchdog_killing" in types, "fresh heartbeat must NOT mask stale events.jsonl"
    assert "watchdog_aborted" in types


def test_watchdog_does_not_fire_on_pre_existing_stale_events_at_startup(tmp_path: "Path") -> None:
    """Regression: watchdog must not immediately kill a freshly-resumed run
    just because events.jsonl is stale FROM A PRIOR CRASH.

    Failure mode observed during run-0504-1212_cf0d recovery:
      - Earlier resume crashed at ts=T, leaving events.jsonl mtime at T
      - User runs `make resume` again at T + 200s
      - supervised-resume spawns the pipeline AND the watchdog
      - Watchdog starts, polls events.jsonl, sees age=200s >> max_idle_s=75s
      - Immediately fires `watchdog_killing` and spawns a duplicate resume
      - Two resumes race on snapshot writes
        -> "Incorrect snapshot status 'running', must be 'created' or 'pending'"

    Fix: watchdog grants a startup grace window. If no new events have
    landed since the watchdog process started AND it hasn't been alive
    for max_idle_s yet, do not fire — give the pipeline time to spin up.
    """
    import json as _json
    import threading
    from unittest.mock import MagicMock, patch

    from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

    output_dir = tmp_path / "output"
    persistence_dir = tmp_path / ".pipeline_runs"
    (output_dir / "test-startup").mkdir(parents=True)
    persistence_dir.mkdir()

    # events.jsonl is OLD (from a prior crashed run). Critical that mtime
    # is far past max_idle_s at the moment the watchdog starts polling.
    events_path = output_dir / "test-startup" / "events.jsonl"
    events_path.write_text(_json.dumps({
        "ts": 1.0, "type": "pipeline_start", "scope": "outer", "run_id": "test-startup",
    }) + "\n")
    ancient = time.time() - 3600
    os.utime(events_path, (ancient, ancient))

    pgid_path = persistence_dir / "test-startup.pgid"
    pgid_path.write_text("999999")

    # Run watchdog in a thread; cancel after enough time to confirm it
    # doesn't fire during the grace window.
    result: dict[str, object] = {}
    kill_called = [0]

    def _record_kill(*args: object, **kwargs: object) -> bool:
        kill_called[0] += 1
        return True

    def _watchdog_thread() -> None:
        try:
            with (
                patch("academic_pipeline.recovery.watchdog._kill_pgid", side_effect=_record_kill),
                patch("academic_pipeline.recovery.watchdog.subprocess.Popen", return_value=MagicMock()),
                patch("academic_pipeline.recovery.watchdog._RESUME_PID_TIMEOUT_S", 1),
            ):
                rc = run_watchdog(WatchdogConfig(
                    thread_id="test-startup",
                    max_idle_s=2,
                    poll_interval_s=1,
                    output_dir=output_dir,
                    persistence_dir=persistence_dir,
                    auto_resume=True,
                    max_strikes=3,
                ))
                result["rc"] = rc
        except Exception as exc:
            result["exc"] = exc

    t = threading.Thread(target=_watchdog_thread, daemon=True)
    t.start()
    # Sleep less than max_idle_s — watchdog should NOT have fired yet.
    time.sleep(1.5)
    assert kill_called[0] == 0, (
        "watchdog fired during startup grace window; pre-existing stale "
        "events.jsonl from prior crash must not trip the watchdog before "
        "the new pipeline has had time to write its first event"
    )
    # The thread will keep running (max_idle_s not yet exceeded since startup);
    # let it run past the grace window to confirm it eventually fires.
    time.sleep(2)
    assert kill_called[0] >= 1, (
        "watchdog should fire after max_idle_s elapsed since its own startup "
        "(not since the pre-existing stale events.jsonl mtime)"
    )
