"""Tier-3 single-file supervisor: spawns pipeline + watchdog as siblings.

The user types ``make run-experiment TOPIC=...`` (unchanged from today).
Under the hood:
  1. supervised_run forks the pipeline as subprocess A (own pgid via setsid)
  2. waits for A to write its first events.jsonl line → reads thread_id
  3. forks the watchdog as subprocess B (own pgid via setsid, --auto-resume)
  4. waits for A to finish; relays A's stdout to current terminal
  5. on A success: cleanly stops B; exits 0
  6. on A SIGKILL by watchdog: returns A's signal exit code (e.g. -15).
     B's auto-resume invokes ``make resume`` which routes through
     ``supervised-resume`` → spawns a fresh supervised_run with its own
     fresh watchdog. The resumed pipeline is therefore NOT orphaned even
     though this supervisor exits. Operator can find it via the latest
     pgid file or `output/<thread_id>/events.jsonl`.
  7. propagates A's final exit code to caller
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


logger = logging.getLogger(__name__)

_THREAD_ID_TIMEOUT_S = 60
_WATCHDOG_GRACEFUL_S = 10


def _strip_flag(args: list[str], *flags: str) -> list[str]:
    """Remove all occurrences of ``flag value`` and ``flag=value`` pairs from args.

    Tolerates typer's "last wins" silently overwriting the user's value with
    the supervisor's value — keeps argv self-consistent and logs honest.
    """
    out: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in flags:
            skip_next = True
            continue
        if any(arg.startswith(f"{flag}=") for flag in flags):
            continue
        out.append(arg)
    return out


def _wait_for_thread_id(
    latest_link: Path,
    timeout_s: float,
    *,
    min_mtime: float | None = None,
) -> str | None:
    """Poll output/latest/events.jsonl until first pipeline_start event lands.

    Args:
        latest_link: Path to the output/latest symlink.
        timeout_s: How long to wait before giving up.
        min_mtime: If provided, only accept events.jsonl files whose mtime is
            newer than this (defends against stale symlink from a previous run).
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            target = latest_link.resolve()
            events_path = target / "events.jsonl"
            if min_mtime is not None and events_path.stat().st_mtime <= min_mtime:
                # Stale file from a previous run; wait for the new one to land
                time.sleep(1)
                continue
            with events_path.open(encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line:
                event = json.loads(first_line)
                if event.get("type") == "pipeline_start" and "run_id" in event:
                    return str(event["run_id"])
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(1)
    return None


def _wait_with_watchdog_supervision(
    pipeline_proc: subprocess.Popen[bytes],
    watchdog_proc: subprocess.Popen[bytes] | None,
    *,
    poll_interval_s: float = 5.0,
) -> int:
    """Wait for pipeline to exit; log a warning if the watchdog dies first.

    The watchdog is the thing that auto-recovers from hangs. If it dies
    silently, the pipeline is no longer protected — degrading back to
    the original 1h+ hang behavior. Log loudly so operator notices.
    """
    watchdog_alive = watchdog_proc is not None
    while True:
        rc = pipeline_proc.poll()
        if rc is not None:
            return rc
        if watchdog_alive and watchdog_proc is not None and watchdog_proc.poll() is not None:
            logger.warning(
                "supervisor: WATCHDOG DIED (exit_code=%s) — pipeline running unprotected from this point",
                watchdog_proc.returncode,
            )
            watchdog_alive = False  # only log once
        time.sleep(poll_interval_s)


def supervised_run(
    *pipeline_args: str,
    output_dir: str = "output",
    no_watchdog: bool = False,
    subcommand: str = "run",
    verbose: bool = True,
    max_recoveries: int = 3,
) -> int:
    """Run the pipeline + watchdog under a single supervisor.

    Args:
        *pipeline_args: Forwarded to ``python -m academic_pipeline <subcommand>``.
        output_dir: Root directory containing per-run subdirectories.
        no_watchdog: If True, skip spawning the watchdog (debugging mode).
        subcommand: Which CLI verb to invoke (``"run"`` for new pipeline,
            ``"resume"`` for crash recovery — passed first positional is the
            topic for "run" or the thread_id for "resume").
        verbose: If True, append ``--verbose`` to the pipeline command.
        max_recoveries: Max consecutive kill+resume cycles before the watchdog
            aborts the run. Forwarded to the watchdog subprocess as
            ``--max-recoveries N``. PRD §6.6.T1.

    Returns:
        The pipeline subprocess's final exit code.
    """
    # Defensive: strip any user-supplied --output-dir / -o so the supervisor's
    # value below is the only one. Typer's last-wins semantics would mask
    # the duplication but it's brittle and confusing in logs.
    cleaned_args = _strip_flag(list(pipeline_args), "--output-dir", "-o")

    pipeline_cmd = [
        sys.executable,
        "-m",
        "academic_pipeline",
        subcommand,
        *cleaned_args,
        "--output-dir",
        output_dir,
    ]
    if verbose:
        pipeline_cmd.append("--verbose")
    t_before_popen = time.time()
    pipeline_proc = subprocess.Popen(
        pipeline_cmd,
        preexec_fn=os.setsid,
    )
    try:
        pipeline_pgid = os.getpgid(pipeline_proc.pid)
    except OSError:
        pipeline_pgid = pipeline_proc.pid
    logger.info(
        "supervisor: pipeline PID=%d PGID=%d started",
        pipeline_proc.pid,
        pipeline_pgid,
    )

    watchdog_proc: subprocess.Popen[bytes] | None = None
    try:
        if not no_watchdog:
            thread_id = _wait_for_thread_id(
                Path(output_dir) / "latest",
                _THREAD_ID_TIMEOUT_S,
                min_mtime=t_before_popen,
            )
            if thread_id is None:
                logger.warning(
                    "supervisor: pipeline did not write thread_id within %ds — running without watchdog",
                    _THREAD_ID_TIMEOUT_S,
                )
            else:
                watchdog_cmd = [
                    sys.executable,
                    "-m",
                    "academic_pipeline",
                    "watchdog",
                    thread_id,
                    "--auto-resume",
                    "--output-dir",
                    output_dir,
                    "--max-recoveries",
                    str(max_recoveries),
                ]
                watchdog_proc = subprocess.Popen(
                    watchdog_cmd,
                    preexec_fn=os.setsid,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info(
                    "supervisor: watchdog PID=%d started for thread_id=%s",
                    watchdog_proc.pid,
                    thread_id,
                )

        return _wait_with_watchdog_supervision(pipeline_proc, watchdog_proc)

    finally:
        if watchdog_proc is not None and watchdog_proc.poll() is None:
            try:
                wpgid = os.getpgid(watchdog_proc.pid)
                os.killpg(wpgid, signal.SIGTERM)
                try:
                    watchdog_proc.wait(timeout=_WATCHDOG_GRACEFUL_S)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(wpgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as exc:
                logger.warning("supervisor: failed to kill watchdog: %s", exc)
