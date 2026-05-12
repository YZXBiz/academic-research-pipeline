"""Test the watchdog Typer subcommand."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from academic_pipeline.cli import app


runner = CliRunner()


def test_watchdog_subcommand_exists() -> None:
    result = runner.invoke(app, ["watchdog", "--help"])
    assert result.exit_code == 0
    assert "thread-id" in result.output.lower() or "thread_id" in result.output.lower()


def test_watchdog_subcommand_invokes_run_watchdog_with_config() -> None:
    with patch("academic_pipeline.recovery.watchdog.run_watchdog", return_value=0) as run_wd:
        result = runner.invoke(
            app,
            ["watchdog", "test-id", "--max-idle", "100", "--auto-resume"],
        )
    assert result.exit_code == 0
    assert run_wd.call_count == 1
    cfg = run_wd.call_args.args[0]
    assert cfg.thread_id == "test-id"
    assert cfg.max_idle_s == 100
    assert cfg.auto_resume is True


def test_supervised_run_subcommand_exists() -> None:
    result = runner.invoke(app, ["supervised-run", "--help"])
    assert result.exit_code == 0
    assert "topic" in result.output.lower()


def test_supervised_run_subcommand_invokes_supervisor() -> None:
    with patch("academic_pipeline.recovery.supervisor.supervised_run", return_value=0) as svr:
        result = runner.invoke(
            app,
            ["supervised-run", "my topic", "--force-experiment", "--no-watchdog"],
        )
    assert result.exit_code == 0
    assert svr.call_count == 1
    args = svr.call_args.args
    kwargs = svr.call_args.kwargs
    assert "my topic" in args
    assert "--force-experiment" in args
    assert kwargs["no_watchdog"] is True


def _has_console_handler() -> bool:
    """Return True if root logger has at least one StreamHandler attached."""
    import logging

    root = logging.getLogger()
    return any(isinstance(h, logging.StreamHandler) for h in root.handlers)


def test_watchdog_command_configures_logging() -> None:
    """watchdog_cmd must attach a console handler so run_watchdog's logs surface."""
    import logging

    logging.getLogger().handlers.clear()
    with patch("academic_pipeline.recovery.watchdog.run_watchdog", return_value=0):
        runner.invoke(app, ["watchdog", "test-id", "--max-idle", "1"])
    assert _has_console_handler()


def test_supervised_run_command_configures_logging() -> None:
    """supervised_run_cmd must attach a console handler so supervisor logs surface."""
    import logging

    logging.getLogger().handlers.clear()
    with patch("academic_pipeline.recovery.supervisor.supervised_run", return_value=0):
        runner.invoke(app, ["supervised-run", "topic", "--no-watchdog"])
    assert _has_console_handler()


def test_supervised_resume_command_configures_logging() -> None:
    """supervised_resume_cmd must attach a console handler so supervisor logs surface."""
    import logging

    logging.getLogger().handlers.clear()
    with patch("academic_pipeline.recovery.supervisor.supervised_run", return_value=0):
        runner.invoke(app, ["supervised-resume", "test-thread", "--no-watchdog"])
    assert _has_console_handler()


# PRD §6.6.T1 — --max-recoveries N flag on watchdog + supervised-run.


def test_watchdog_max_recoveries_threads_through_to_config() -> None:
    """--max-recoveries N must populate WatchdogConfig.max_strikes."""
    with patch("academic_pipeline.recovery.watchdog.run_watchdog", return_value=0) as run_wd:
        result = runner.invoke(
            app,
            ["watchdog", "test-id", "--max-recoveries", "5"],
        )
    assert result.exit_code == 0, result.output
    cfg = run_wd.call_args.args[0]
    assert cfg.max_strikes == 5


def test_watchdog_max_recoveries_default_is_3() -> None:
    """When neither --max-recoveries nor --max-strikes is passed, default = 3."""
    with patch("academic_pipeline.recovery.watchdog.run_watchdog", return_value=0) as run_wd:
        result = runner.invoke(app, ["watchdog", "test-id"])
    assert result.exit_code == 0
    cfg = run_wd.call_args.args[0]
    assert cfg.max_strikes == 3


def test_watchdog_legacy_max_strikes_still_works() -> None:
    """Backward-compat: --max-strikes remains accepted and threads through."""
    with patch("academic_pipeline.recovery.watchdog.run_watchdog", return_value=0) as run_wd:
        result = runner.invoke(app, ["watchdog", "test-id", "--max-strikes", "7"])
    assert result.exit_code == 0
    cfg = run_wd.call_args.args[0]
    assert cfg.max_strikes == 7


def test_supervised_run_max_recoveries_forwards_to_supervisor() -> None:
    """supervised-run --max-recoveries N forwards as max_recoveries kwarg."""
    with patch("academic_pipeline.recovery.supervisor.supervised_run", return_value=0) as svr:
        result = runner.invoke(
            app,
            ["supervised-run", "topic", "--no-watchdog", "--max-recoveries", "4"],
        )
    assert result.exit_code == 0, result.output
    kwargs = svr.call_args.kwargs
    assert kwargs.get("max_recoveries") == 4
