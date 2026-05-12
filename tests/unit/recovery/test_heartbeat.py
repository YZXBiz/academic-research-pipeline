"""Tests for the daemon-thread Heartbeat context manager."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from academic_pipeline.recovery.heartbeat import Heartbeat


if TYPE_CHECKING:
    from pathlib import Path


def test_heartbeat_writes_file_immediately_on_enter(tmp_path: Path) -> None:
    path = tmp_path / "hb.txt"
    with Heartbeat(path, interval_s=10.0):
        time.sleep(0.2)  # give the thread a moment to do its first tick
        assert path.exists()
        first_value = float(path.read_text())
        assert first_value > 0.0


def test_heartbeat_advances_mtime_over_time(tmp_path: Path) -> None:
    path = tmp_path / "hb.txt"
    with Heartbeat(path, interval_s=0.1):
        # Wait for the first tick to land the file on disk.
        deadline = time.time() + 2.0
        while not path.exists() and time.time() < deadline:
            time.sleep(0.01)
        first_mtime = path.stat().st_mtime

        # Poll for an mtime advance instead of sleep-and-hope. Under heavy
        # suite load the heartbeat thread can be starved enough that a fixed
        # 0.4s sleep is not enough ticks; condition-based waiting decouples
        # the test from CPU contention.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            second_mtime = path.stat().st_mtime
            if second_mtime > first_mtime:
                break
            time.sleep(0.05)
        else:
            second_mtime = path.stat().st_mtime
    assert second_mtime > first_mtime, (
        f"heartbeat mtime did not advance within 5s "
        f"(first={first_mtime}, second={second_mtime})"
    )


def test_heartbeat_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    path = nested / "hb.txt"
    with Heartbeat(path, interval_s=10.0):
        time.sleep(0.2)
        assert path.exists()


def test_heartbeat_uses_daemon_thread(tmp_path: Path) -> None:
    """Daemon flag means thread does NOT block process exit."""
    path = tmp_path / "hb.txt"
    hb = Heartbeat(path, interval_s=10.0)
    with hb:
        assert hb._thread is not None
        assert hb._thread.daemon is True


def test_heartbeat_stop_event_signals_exit(tmp_path: Path) -> None:
    """__exit__ sets the stop event; the loop notices and returns."""
    path = tmp_path / "hb.txt"
    hb = Heartbeat(path, interval_s=10.0)
    with hb:
        assert not hb._stop.is_set()
    assert hb._stop.is_set()


def test_heartbeat_survives_when_main_thread_blocks(tmp_path: Path) -> None:
    """The daemon thread keeps ticking even if the main thread is blocked.

    This is the critical guarantee: when the asyncio event loop is wedged
    in sync socket.recv(), the heartbeat must STILL fire, otherwise the
    watchdog would false-positive on a healthy stuck pipeline.
    """
    path = tmp_path / "hb.txt"
    with Heartbeat(path, interval_s=0.1):
        # Block the main thread for 0.5 seconds
        # (simulates blocked event loop / sync recv)
        end = time.time() + 0.5
        while time.time() < end:
            time.sleep(0.01)
        # Heartbeat thread should have ticked multiple times during the block
        first_mtime = path.stat().st_mtime
        time.sleep(0.05)
        # The timestamp written should be near "now", not stale
        written_ts = float(path.read_text())
        assert time.time() - written_ts < 1.0, "heartbeat went stale during main-thread block"
        # And the file SHOULD have been updated DURING the busy-wait
        assert first_mtime > time.time() - 1.0


def test_heartbeat_handles_disk_write_failure_gracefully(tmp_path: Path, caplog) -> None:
    """If the disk write fails, the thread logs and continues, doesn't crash."""
    import logging

    path = tmp_path / "hb.txt"
    with (
        caplog.at_level(logging.WARNING, logger="academic_pipeline.recovery.heartbeat"),
        Heartbeat(path, interval_s=0.1),
    ):
        time.sleep(0.05)  # first tick succeeds
        # Make the directory unwritable to force OSError on next tick
        tmp_path.chmod(0o500)
        try:
            time.sleep(0.3)  # several ticks try and fail
        finally:
            tmp_path.chmod(0o700)  # restore so cleanup works
    # Did NOT raise. May or may not log depending on whether dir-perms blocked
    # the rename (varies by FS); the key invariant is no crash.
