"""Hang-recovery layer for the academic pipeline.

Layered defense: TCP keepalive → bounded agent calls → daemon-thread
heartbeat → external watchdog → supervisor wrapper.

Public API:
    bounded_agent_run, AgentTimeoutError       # for code that calls agent.run
    Heartbeat, ProcessLock                     # context managers used by Pipeline
    make_keepalive_async_client                # for provider construction
    supervised_run, run_watchdog, WatchdogConfig  # CLI entry points
"""

from __future__ import annotations

from academic_pipeline.recovery.bounded_run import AgentTimeoutError, bounded_agent_run
from academic_pipeline.recovery.heartbeat import Heartbeat
from academic_pipeline.recovery.process_state import ProcessLock
from academic_pipeline.recovery.supervisor import supervised_run
from academic_pipeline.recovery.transport import make_keepalive_async_client
from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog


__all__ = [
    "AgentTimeoutError",
    "Heartbeat",
    "ProcessLock",
    "WatchdogConfig",
    "bounded_agent_run",
    "make_keepalive_async_client",
    "run_watchdog",
    "supervised_run",
]
