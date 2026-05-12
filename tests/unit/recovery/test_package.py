"""Smoke test that the recovery package is importable."""

from __future__ import annotations


def test_recovery_package_importable() -> None:
    import academic_pipeline.recovery  # noqa: F401


def test_recovery_public_api_re_exports_components() -> None:
    from academic_pipeline.recovery import (
        AgentTimeoutError,
        Heartbeat,
        ProcessLock,
        WatchdogConfig,
        bounded_agent_run,
        make_keepalive_async_client,
        run_watchdog,
        supervised_run,
    )

    assert all(callable(x) or isinstance(x, type) for x in (
        AgentTimeoutError, Heartbeat, ProcessLock, WatchdogConfig,
        bounded_agent_run, make_keepalive_async_client, run_watchdog, supervised_run,
    ))
