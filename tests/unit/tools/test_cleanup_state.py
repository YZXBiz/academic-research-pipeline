"""Tests for tools/cleanup_state.py — PRD §6.9.T5 incompatible-state cleanup.

Covers:
- Dry-run by default (no --confirm) → reports but moves nothing.
- --confirm + default archive mode → moves to .pipeline_runs/_archive/<ts>/.
- --confirm + --purge → deletes outright.
- Idempotent: re-running on a cleaned dir is a no-op.
- Files at the current PIPELINE_STATE_SCHEMA_VERSION are kept.
- Files inside _archive/ are skipped (don't re-archive).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def _legacy_state(filename: str = "t-1_state.json") -> tuple[str, str]:
    """Return (filename, JSON body) for a pre-v2.5.0 state file (no version key)."""
    return filename, json.dumps({"topic": "x", "run_id": "t-1"})


def _current_state(filename: str = "t-2_state.json") -> tuple[str, str]:
    """Return (filename, JSON body) for a state file at the current version."""
    from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

    return filename, json.dumps(
        {
            "topic": "y",
            "run_id": "t-2",
            "_schema_version": PIPELINE_STATE_SCHEMA_VERSION,
        }
    )


def _seed(runs_dir: Path, files: list[tuple[str, str]]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    for name, body in files:
        (runs_dir / name).write_text(body)


def test_dry_run_reports_but_moves_nothing(tmp_path: Path) -> None:
    """Without --confirm the script reports incompatible files but takes no action."""
    from tools.cleanup_state import cleanup_state

    runs = tmp_path / ".pipeline_runs"
    legacy_name, legacy_body = _legacy_state()
    _seed(runs, [(legacy_name, legacy_body)])

    summary = cleanup_state(pipeline_runs_dir=runs, confirm=False, purge=False)

    # Reporting found the legacy file
    assert summary.incompatible_count == 1
    assert legacy_name in [f.name for f in summary.incompatible_files]
    # But the file is still present and unchanged
    assert (runs / legacy_name).exists()
    assert (runs / legacy_name).read_text() == legacy_body
    # No archive dir was created
    assert not (runs / "_archive").exists()


def test_confirm_archives_incompatible_files_by_default(tmp_path: Path) -> None:
    """--confirm without --purge moves files to _archive/<ts>/."""
    from tools.cleanup_state import cleanup_state

    runs = tmp_path / ".pipeline_runs"
    legacy_name, legacy_body = _legacy_state()
    current_name, current_body = _current_state()
    _seed(runs, [(legacy_name, legacy_body), (current_name, current_body)])

    summary = cleanup_state(pipeline_runs_dir=runs, confirm=True, purge=False)

    assert summary.archived_count == 1
    assert summary.purged_count == 0
    # Legacy file moved out of the runs dir
    assert not (runs / legacy_name).exists()
    # Current file untouched
    assert (runs / current_name).exists()
    # An _archive subdir exists with the legacy file inside
    archive_dir = runs / "_archive"
    assert archive_dir.is_dir()
    archived = list(archive_dir.rglob(legacy_name))
    assert len(archived) == 1
    assert archived[0].read_text() == legacy_body


def test_purge_actually_deletes_when_confirmed(tmp_path: Path) -> None:
    """--purge + --confirm deletes incompatible files outright (no archive copy)."""
    from tools.cleanup_state import cleanup_state

    runs = tmp_path / ".pipeline_runs"
    legacy_name, legacy_body = _legacy_state()
    _seed(runs, [(legacy_name, legacy_body)])

    summary = cleanup_state(pipeline_runs_dir=runs, confirm=True, purge=True)

    assert summary.archived_count == 0
    assert summary.purged_count == 1
    assert not (runs / legacy_name).exists()
    # No archive copy was made
    assert not (runs / "_archive").exists()


def test_skips_files_already_in_archive(tmp_path: Path) -> None:
    """Files under _archive/ are ignored on subsequent runs."""
    from tools.cleanup_state import cleanup_state

    runs = tmp_path / ".pipeline_runs"
    archive_subdir = runs / "_archive" / "20250101_120000"
    archive_subdir.mkdir(parents=True)
    legacy_name, legacy_body = _legacy_state()
    (archive_subdir / legacy_name).write_text(legacy_body)

    summary = cleanup_state(pipeline_runs_dir=runs, confirm=True, purge=False)

    assert summary.incompatible_count == 0
    assert summary.archived_count == 0
    # Original archive copy untouched
    assert (archive_subdir / legacy_name).exists()


def test_idempotent_no_op_on_already_clean_dir(tmp_path: Path) -> None:
    """Running on a dir that has only current-version files is a no-op."""
    from tools.cleanup_state import cleanup_state

    runs = tmp_path / ".pipeline_runs"
    current_name, current_body = _current_state()
    _seed(runs, [(current_name, current_body)])

    summary = cleanup_state(pipeline_runs_dir=runs, confirm=True, purge=False)

    assert summary.incompatible_count == 0
    assert summary.archived_count == 0
    assert (runs / current_name).exists()


def test_handles_missing_runs_dir_gracefully(tmp_path: Path) -> None:
    """When the .pipeline_runs/ dir doesn't exist, return a zero-count summary."""
    from tools.cleanup_state import cleanup_state

    summary = cleanup_state(
        pipeline_runs_dir=tmp_path / "does-not-exist",
        confirm=True,
        purge=False,
    )
    assert summary.incompatible_count == 0
    assert summary.archived_count == 0
    assert summary.purged_count == 0


def test_cli_subcommand_exists_and_runs_dry_by_default(tmp_path: Path) -> None:
    """`academic-pipeline cleanup-state --pipeline-runs-dir <tmp>` is callable."""
    from typer.testing import CliRunner

    from academic_pipeline.cli import app

    runner = CliRunner()
    runs = tmp_path / ".pipeline_runs"
    legacy_name, legacy_body = _legacy_state()
    _seed(runs, [(legacy_name, legacy_body)])

    result = runner.invoke(
        app,
        ["cleanup-state", "--pipeline-runs-dir", str(runs)],
    )
    # Dry-run with incompatible file present → exit 1 (signals "needs cleanup").
    assert result.exit_code == 1
    # File is still there (dry-run).
    assert (runs / legacy_name).exists()


def test_cli_subcommand_confirm_archives(tmp_path: Path) -> None:
    """`academic-pipeline cleanup-state --confirm` actually moves files."""
    from typer.testing import CliRunner

    from academic_pipeline.cli import app

    runner = CliRunner()
    runs = tmp_path / ".pipeline_runs"
    legacy_name, legacy_body = _legacy_state()
    _seed(runs, [(legacy_name, legacy_body)])

    result = runner.invoke(
        app,
        ["cleanup-state", "--pipeline-runs-dir", str(runs), "--confirm"],
    )
    assert result.exit_code == 0
    assert not (runs / legacy_name).exists()
    assert any((runs / "_archive").rglob(legacy_name))
