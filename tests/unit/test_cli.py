"""TDD Cycle 2: Typer CLI tests."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from academic_pipeline.cli import app


runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from Typer's rich-formatted output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_help_shows_description():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Academic Research Pipeline" in result.output


def test_run_command_exists():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "topic" in _strip_ansi(result.output).lower()


def test_research_command_does_not_exist():
    result = runner.invoke(app, ["research", "--help"])
    assert result.exit_code != 0


def test_write_command_does_not_exist():
    result = runner.invoke(app, ["write", "--help"])
    assert result.exit_code != 0


def test_review_command_does_not_exist():
    result = runner.invoke(app, ["review", "--help"])
    assert result.exit_code != 0


def test_run_requires_topic():
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0


def test_resume_command_exists():
    result = runner.invoke(app, ["resume", "--help"])
    assert result.exit_code == 0
    assert "thread" in _strip_ansi(result.output).lower()


def test_resume_unknown_thread_id(tmp_path):
    """Resume with a non-existent thread-id should error."""
    from unittest.mock import patch

    with patch("academic_pipeline.cli._init"):
        result = runner.invoke(app, ["resume", "nonexistent-thread-id"])

    assert result.exit_code == 1


def test_resume_loads_topic_from_sqlite(tmp_path):
    """Resume should load topic from saved state and pass it to Pipeline."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    from academic_pipeline.sdk.result import PipelineResult

    mock_result = PipelineResult({"topic": "quantum computing", "pipeline_status": "completed", "stages": {}})

    with (
        patch("academic_pipeline.cli._init"),
        patch("academic_pipeline.cli.SqliteStatePersistence") as mock_persist_cls,
        patch("academic_pipeline.sdk.pipeline.Pipeline") as mock_pipeline_cls,
    ):
        mock_persist = MagicMock()
        mock_persist._load_pipeline_state_sync.return_value = json.dumps({"topic": "quantum computing"})
        mock_persist_cls.return_value = mock_persist

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=mock_result)
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["resume", "test-resume"])

        assert result.exit_code == 0
        mock_pipeline_cls.assert_called_once()
        call_kwargs = mock_pipeline_cls.call_args
        assert call_kwargs[0][0] == "quantum computing"
        assert call_kwargs[1]["thread_id"] == "test-resume"


def test_run_accepts_verbose_flag():
    output = _strip_ansi(runner.invoke(app, ["run", "--help"]).output)
    assert "--verbose" in output


# --- Coverage gaps: error handling paths in _run_and_show ---


def test_run_command_error_shows_failure_message():
    """When Pipeline.run() raises, CLI should echo error and exit with code 1."""
    from unittest.mock import MagicMock, patch

    with (
        patch("academic_pipeline.cli._init"),
        patch("academic_pipeline.sdk.pipeline.Pipeline") as mock_pipeline_cls,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.run.side_effect = RuntimeError("LLM API failure")
        mock_pipeline_cls.return_value = mock_pipeline

        result = runner.invoke(app, ["run", "test topic"])

        assert result.exit_code == 1
        assert "Pipeline failed" in result.output


def test_run_command_with_output_dir_saves_artifacts(tmp_path):
    """When --output-dir is provided, CLI should call result.save()."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from academic_pipeline.sdk.result import PipelineResult

    mock_result = PipelineResult({"topic": "AI", "pipeline_status": "completed", "stages": {}})

    with (
        patch("academic_pipeline.cli._init"),
        patch("academic_pipeline.sdk.pipeline.Pipeline") as mock_pipeline_cls,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(return_value=mock_result)
        mock_pipeline_cls.return_value = mock_pipeline

        out_dir = str(tmp_path / "artifacts")
        result = runner.invoke(app, ["run", "AI", "--output-dir", out_dir])

        assert result.exit_code == 0
        assert "Artifacts saved" in result.output


def test_init_configures_logging():
    """_init should call configure_logging with verbose and config-driven params."""
    from unittest.mock import patch

    with patch("academic_pipeline.cli.configure_logging") as mock_log:
        from academic_pipeline.cli import CheckpointerBackend, _init

        _init(CheckpointerBackend.MEMORY, verbose=True, json_logs=False)

        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert call_args[0][0] is True  # verbose
        assert call_args[1]["json_logs"] is False


def test_init_without_checkpointer():
    """_init without checkpointer should still configure logging."""
    from unittest.mock import patch

    with patch("academic_pipeline.cli.configure_logging") as mock_log:
        from academic_pipeline.cli import _init

        _init(None, verbose=False, json_logs=False)

        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert call_args[0][0] is False  # verbose
        assert call_args[1]["json_logs"] is False
