"""External hang-detection watchdog for the pipeline.

Polls ``events.jsonl`` mtime as the proof-of-progress signal. If it is
stale beyond ``max_idle_s``, sends SIGTERM to the pipeline's process group
via the ``.pgid`` file, waits 10s, then SIGKILL if still alive. Optionally
auto-resumes via ``make resume``. 3-strikes escalation aborts if recoveries
don't actually restart progress.

heartbeat.txt is NOT used for stall detection. The heartbeat is written by
a daemon thread which keeps ticking even when the main code is hung in an
``await`` (e.g. PydanticAI/Anthropic SDK waiting for SSE chunks that never
arrive after the proxy drops the stream). Trusting heartbeat for stalls
masked this exact failure mode in run-0504-1212_cf0d (1h41m wedged with
fresh heartbeat). Events.jsonl is the only signal that proves the pipeline
is making real progress.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_GRACEFUL_KILL_S = 10
_RESUME_PID_TIMEOUT_S = 60


@dataclass(frozen=True)
class WatchdogConfig:
    """Immutable configuration for ``run_watchdog``."""

    thread_id: str
    # 75s was the original default and proved much too aggressive: legitimate
    # research nodes (SourceVerificationNode loops over Semantic Scholar +
    # CrossRef + Retraction Watch for every bibliography source, BibliographyNode
    # batches Exa neural searches) silently spend 60-120s between events.jsonl
    # writes. False-positive kills were observed in run-0504-1802_ec44 at
    # age_s=76.6. The watchdog's purpose is to catch HOURS-long LLM proxy SSE
    # wedges, not minutes-long-but-progressing nodes. 600s (10 min) gives a
    # comfortable headroom over the slowest known node while still recovering
    # the multi-hour wedges the watchdog exists for.
    max_idle_s: int = 600
    poll_interval_s: int = 30
    output_dir: Path = field(default_factory=lambda: Path("output"))
    persistence_dir: Path = field(default_factory=lambda: Path(".pipeline_runs"))
    auto_resume: bool = False
    max_strikes: int = 3


def _age(path: Path) -> float | None:
    """Seconds since path was last modified, or None if missing."""
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return None


def _read_int(path: Path) -> int | None:
    """Read an integer from path; return None if missing or invalid."""
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _emit_watchdog_event(events_path: Path, event_type: str, **fields: Any) -> None:
    """Append a watchdog event to events.jsonl using the same format as the pipeline."""
    record = {"ts": time.time(), "type": event_type, "scope": "watchdog", **fields}
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _kill_pgid(pgid: int) -> bool:
    """SIGTERM the process group, wait 10s, SIGKILL if still alive.

    Returns True if the group is dead by the end (or was already gone).

    Catches both ProcessLookupError (ESRCH — group never existed or already
    reaped) and PermissionError (EPERM — on macOS, a reaped pgid that has
    been recycled by another user's process; we treat this as "dead from our
    perspective" since we couldn't kill it anyway).
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # PermissionError: PID reused by a process owned by another user
        # after the original group was reaped. Treat as dead.
        return True
    for _ in range(_GRACEFUL_KILL_S):
        time.sleep(1)
        try:
            os.killpg(pgid, 0)  # signal 0 = liveness probe
        except (ProcessLookupError, PermissionError):
            return True
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)
    time.sleep(2)
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return True
    return False  # still alive after SIGKILL — extreme failure


def _count_pipeline_events(path: Path) -> int:
    """Count events.jsonl lines emitted by the pipeline (excludes scope=watchdog).

    The 3-strikes safety net measures whether the PIPELINE has made progress
    between stalls. The watchdog itself emits events (watchdog_killing, _killed,
    _resuming, _resumed, _aborted) on every kill cycle — counting those would
    make event_count strictly increase between stalls and the strike counter
    would never reach max_strikes, defeating the safety net.
    """
    try:
        n = 0
        with path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    if json.loads(stripped).get("scope") != "watchdog":
                        n += 1
                except json.JSONDecodeError:
                    n += 1  # malformed line — treat as pipeline event (conservative)
        return n
    except FileNotFoundError:
        return 0


def run_watchdog(cfg: WatchdogConfig) -> int:
    """Run the watchdog loop. Returns 0 on graceful exit, 2 on 3-strikes abort."""
    events_path = cfg.output_dir / cfg.thread_id / "events.jsonl"
    pgid_path = cfg.persistence_dir / f"{cfg.thread_id}.pgid"

    strikes = 0
    last_event_count = -1
    # Snapshot the events.jsonl line count at startup. This is the baseline:
    # if the pipeline writes ANY new line after watchdog starts, we know it's
    # making progress regardless of what the absolute mtime says. Without this
    # baseline, watchdog fires immediately on resume into a previously-crashed
    # run because events.jsonl mtime is already minutes-old (from the crash)
    # the moment the watchdog starts polling.
    startup_event_count = _count_pipeline_events(events_path)
    startup_ts = time.time()

    while True:
        time.sleep(cfg.poll_interval_s)
        # Stall detection is on events.jsonl mtime ONLY. The heartbeat daemon
        # thread keeps ticking even when the main async code is hung in an
        # await — using min(events_age, heart_age) lets a fresh heartbeat mask
        # a stale events file, which is exactly how run-0504-1212_cf0d went
        # 1h41m unrecovered. Events.jsonl mtime is the only signal that
        # proves the pipeline is making real progress.
        age = _age(events_path)
        if age is None:
            continue  # pipeline hasn't started writing events yet

        # Startup grace: if the pipeline has written any new event since the
        # watchdog started, we know it's making progress and the absolute
        # mtime (which may be stale from a prior crashed run) is irrelevant.
        # If it hasn't written anything yet, only fire after max_idle_s have
        # actually elapsed since watchdog start (not since the prior crash).
        if _count_pipeline_events(events_path) > startup_event_count:
            # Pipeline has emitted at least one event since we started.
            # Trust events.jsonl mtime from here on.
            pass
        elif (time.time() - startup_ts) < cfg.max_idle_s:
            # Still inside the post-startup grace window.
            continue

        if age < cfg.max_idle_s:
            continue  # healthy

        # Stalled. Track strike progression based on whether new PIPELINE events
        # landed. Watchdog's own events are filtered out — if we counted them,
        # the kill+resume cycle would always look like progress and the safety
        # net would never trip.
        event_count = _count_pipeline_events(events_path)
        if event_count == last_event_count:
            strikes += 1
            if strikes >= cfg.max_strikes:
                _emit_watchdog_event(
                    events_path,
                    "watchdog_aborted",
                    reason=f"{cfg.max_strikes} consecutive recoveries with no progress",
                    strikes=strikes,
                )
                return 2
        else:
            strikes = 1
            last_event_count = event_count

        pgid = _read_int(pgid_path)
        killed = True
        if pgid is not None:
            _emit_watchdog_event(
                events_path,
                "watchdog_killing",
                pgid=pgid,
                age_s=round(age, 1),
                strike=strikes,
            )
            killed = _kill_pgid(pgid)
            _emit_watchdog_event(events_path, "watchdog_killed", killed_cleanly=killed)

        if cfg.auto_resume:
            # Remove stale pgid file so the polling loop below only sees the
            # NEW pipeline's pgid (the killed pipeline's ProcessLock.__exit__
            # was bypassed by SIGKILL, leaving the file on disk).
            pgid_path.unlink(missing_ok=True)

            _emit_watchdog_event(events_path, "watchdog_resuming")
            # Invoke supervised-resume directly (NOT `make resume`) so the
            # resumed pipeline gets its own supervisor + watchdog instead of
            # running orphan. Routes through Python module so it works in
            # environments without make (CI, Docker, Windows-WSL).
            subprocess.Popen(
                [sys.executable, "-m", "academic_pipeline", "supervised-resume",
                 cfg.thread_id, "--output-dir", str(cfg.output_dir)],
                preexec_fn=os.setsid,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(_RESUME_PID_TIMEOUT_S):
                time.sleep(1)
                if _read_int(pgid_path) is not None:
                    _emit_watchdog_event(events_path, "watchdog_resumed")
                    break
        else:
            return 0
