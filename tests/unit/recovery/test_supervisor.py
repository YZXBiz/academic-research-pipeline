"""Tests for the supervised_run Tier-3 launcher."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from academic_pipeline.recovery.supervisor import _wait_for_thread_id, supervised_run


if TYPE_CHECKING:
    from pathlib import Path


def test_wait_for_thread_id_returns_none_when_link_missing(tmp_path: Path) -> None:
    assert _wait_for_thread_id(tmp_path / "latest", timeout_s=0.5) is None


def test_wait_for_thread_id_returns_id_from_first_event(tmp_path: Path) -> None:
    target = tmp_path / "run-123"
    target.mkdir()
    events = target / "events.jsonl"
    events.write_text(
        json.dumps(
            {"ts": 1.0, "type": "pipeline_start", "run_id": "run-123", "topic": "x", "resumed": False},
        )
        + "\n",
    )
    (tmp_path / "latest").symlink_to(target.name)
    assert _wait_for_thread_id(tmp_path / "latest", timeout_s=2.0) == "run-123"


def test_wait_for_thread_id_returns_none_on_no_pipeline_start(tmp_path: Path) -> None:
    target = tmp_path / "run-x"
    target.mkdir()
    events = target / "events.jsonl"
    events.write_text(json.dumps({"type": "something_else"}) + "\n")
    (tmp_path / "latest").symlink_to(target.name)
    assert _wait_for_thread_id(tmp_path / "latest", timeout_s=0.5) is None


def test_supervised_run_returns_pipeline_exit_code(tmp_path: Path) -> None:
    """Mock subprocess.Popen so we don't actually run the pipeline."""
    fake_pipeline = MagicMock()
    fake_pipeline.pid = 99999
    fake_pipeline.poll.return_value = 7  # nonzero exit on first poll
    fake_pipeline.returncode = 7

    with (
        patch("academic_pipeline.recovery.supervisor.subprocess.Popen", return_value=fake_pipeline) as popen,
        patch("academic_pipeline.recovery.supervisor._wait_for_thread_id", return_value=None),
        patch("academic_pipeline.recovery.supervisor.os.getpgid", return_value=99999),
    ):
        rc = supervised_run("topic-x", output_dir=str(tmp_path), no_watchdog=True)

    assert rc == 7
    assert popen.call_count == 1  # only pipeline, no watchdog (no_watchdog=True)


def test_supervised_run_skips_watchdog_when_no_watchdog_flag_set(tmp_path: Path) -> None:
    fake_pipeline = MagicMock()
    fake_pipeline.pid = 99999
    fake_pipeline.poll.return_value = 0
    fake_pipeline.returncode = 0

    with (
        patch("academic_pipeline.recovery.supervisor.subprocess.Popen", return_value=fake_pipeline) as popen,
        patch("academic_pipeline.recovery.supervisor._wait_for_thread_id") as wait_id,
        patch("academic_pipeline.recovery.supervisor.os.getpgid", return_value=99999),
    ):
        supervised_run("topic", output_dir=str(tmp_path), no_watchdog=True)

    assert popen.call_count == 1
    wait_id.assert_not_called()


def test_supervised_run_starts_watchdog_when_thread_id_resolves(tmp_path: Path) -> None:
    fake_pipeline = MagicMock()
    fake_pipeline.pid = 11111
    fake_pipeline.poll.return_value = 0
    fake_pipeline.returncode = 0
    fake_watchdog = MagicMock()
    fake_watchdog.pid = 22222
    fake_watchdog.poll.return_value = None  # still alive at finally
    fake_watchdog.wait.return_value = 0

    popen_calls: list[list[str]] = []

    def _popen_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        popen_calls.append(cmd)
        if "watchdog" in cmd:
            return fake_watchdog
        return fake_pipeline

    with (
        patch("academic_pipeline.recovery.supervisor.subprocess.Popen", side_effect=_popen_side_effect),
        patch("academic_pipeline.recovery.supervisor._wait_for_thread_id", return_value="run-xyz"),
        patch("academic_pipeline.recovery.supervisor.os.getpgid", side_effect=lambda pid: pid),
        patch("academic_pipeline.recovery.supervisor.os.killpg") as killpg,
    ):
        supervised_run("topic", output_dir=str(tmp_path))

    # Two Popen calls: pipeline + watchdog
    assert len(popen_calls) == 2
    assert any("watchdog" in cmd for cmd in popen_calls)
    # Watchdog killed in finally
    killpg.assert_called()


def test_wait_with_watchdog_supervision_logs_when_watchdog_dies(caplog: object) -> None:
    """If the watchdog process exits before the pipeline, supervisor logs a warning."""
    import logging

    from academic_pipeline.recovery.supervisor import _wait_with_watchdog_supervision

    pipeline_proc = MagicMock()
    # Pipeline exits cleanly on the second poll
    pipeline_proc.poll.side_effect = [None, 0]
    pipeline_proc.returncode = 0

    watchdog_proc = MagicMock()
    # Watchdog dies on the first poll (before pipeline)
    watchdog_proc.poll.return_value = 137  # SIGKILLed
    watchdog_proc.returncode = 137

    with caplog.at_level(logging.WARNING, logger="academic_pipeline.recovery.supervisor"):
        rc = _wait_with_watchdog_supervision(pipeline_proc, watchdog_proc, poll_interval_s=0.01)

    assert rc == 0
    assert any("WATCHDOG DIED" in rec.message for rec in caplog.records)


def test_wait_with_watchdog_supervision_returns_pipeline_exit_code() -> None:
    """When pipeline exits, supervisor returns its exit code (regardless of watchdog state)."""
    from academic_pipeline.recovery.supervisor import _wait_with_watchdog_supervision

    pipeline_proc = MagicMock()
    pipeline_proc.poll.return_value = 42
    pipeline_proc.returncode = 42

    rc = _wait_with_watchdog_supervision(pipeline_proc, None, poll_interval_s=0.01)
    assert rc == 42


def test_wait_for_thread_id_rejects_stale_symlink(tmp_path: Path) -> None:
    """If output/latest points at a stale events.jsonl with pipeline_start,
    don't return its run_id — wait for the NEW run to write its file.
    """
    import os as _os
    import time

    # Stale run dir (older than min_mtime cutoff)
    stale = tmp_path / "run-old"
    stale.mkdir()
    (stale / "events.jsonl").write_text(
        json.dumps({"ts": 1.0, "type": "pipeline_start", "run_id": "run-old", "topic": "x", "resumed": False}) + "\n",
    )
    # Force ancient mtime
    ancient = time.time() - 3600
    _os.utime(stale / "events.jsonl", (ancient, ancient))

    (tmp_path / "latest").symlink_to(stale.name)

    # min_mtime = now means "anything older than now is stale"
    result = _wait_for_thread_id(tmp_path / "latest", timeout_s=0.5, min_mtime=time.time())
    assert result is None


def test_supervised_run_resume_subcommand_invokes_resume_verb(tmp_path: "Path") -> None:
    """supervised_run(subcommand='resume') must invoke `python -m academic_pipeline resume`."""
    from unittest.mock import MagicMock, patch

    from academic_pipeline.recovery.supervisor import supervised_run

    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], **_kwargs: object) -> MagicMock:
        captured.append(cmd)
        proc = MagicMock()
        proc.poll.return_value = 0  # exit immediately
        proc.pid = 99999
        return proc

    with (
        patch("academic_pipeline.recovery.supervisor.subprocess.Popen", side_effect=_fake_popen),
        patch("academic_pipeline.recovery.supervisor.os.getpgid", return_value=99999),
        patch("academic_pipeline.recovery.supervisor._wait_for_thread_id", return_value=None),
    ):
        supervised_run(
            "test-thread-id",
            output_dir=str(tmp_path / "out"),
            no_watchdog=True,
            subcommand="resume",
            verbose=False,
        )

    assert captured, "expected at least one Popen call"
    cmd = captured[0]
    assert "resume" in cmd
    assert "run" not in cmd or cmd.index("resume") > cmd.index("run")  # the 'resume' verb wins
    assert "test-thread-id" in cmd
    assert "--verbose" not in cmd  # quiet honored


def test_supervised_run_strips_duplicate_output_dir_from_args(tmp_path: "Path") -> None:
    """User-supplied --output-dir in pipeline_args is stripped; supervisor's wins cleanly."""
    from unittest.mock import MagicMock, patch

    from academic_pipeline.recovery.supervisor import supervised_run

    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], **_kwargs: object) -> MagicMock:
        captured.append(cmd)
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.pid = 99999
        return proc

    with (
        patch("academic_pipeline.recovery.supervisor.subprocess.Popen", side_effect=_fake_popen),
        patch("academic_pipeline.recovery.supervisor.os.getpgid", return_value=99999),
        patch("academic_pipeline.recovery.supervisor._wait_for_thread_id", return_value=None),
    ):
        supervised_run(
            "topic",
            "--output-dir", "wrong-place",  # user-supplied
            "--force-experiment",
            output_dir=str(tmp_path / "right-place"),
            no_watchdog=True,
        )

    cmd = captured[0]
    # only one --output-dir should appear, with the supervisor's value
    assert cmd.count("--output-dir") == 1
    assert str(tmp_path / "right-place") in cmd
    assert "wrong-place" not in cmd
    # but other args survived
    assert "--force-experiment" in cmd


def test_strip_flag_handles_equals_form_and_short_flag() -> None:
    """_strip_flag removes both `--flag value`, `--flag=value`, and `-o value` forms."""
    from academic_pipeline.recovery.supervisor import _strip_flag

    assert _strip_flag(["topic", "--output-dir", "foo", "--force-experiment"], "--output-dir", "-o") == [
        "topic", "--force-experiment",
    ]
    assert _strip_flag(["topic", "--output-dir=foo", "--force-experiment"], "--output-dir", "-o") == [
        "topic", "--force-experiment",
    ]
    assert _strip_flag(["topic", "-o", "foo", "--force-experiment"], "--output-dir", "-o") == [
        "topic", "--force-experiment",
    ]
    assert _strip_flag(["topic", "--force-experiment"], "--output-dir", "-o") == [
        "topic", "--force-experiment",
    ]
