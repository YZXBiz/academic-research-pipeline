"""dagster_runner constructs the right command + reports results."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from academic_pipeline.experiment.dagster_runner import run_dagster_job


def test_run_dagster_job_invokes_uv_run(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("schema_version: 1")
    (tmp_path / "src" / "pipeline").mkdir(parents=True)
    (tmp_path / "src" / "pipeline" / "definitions.py").write_text("# stub")
    (tmp_path / "results.json").write_text("{}")
    completed = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch(
        "academic_pipeline.experiment.dagster_runner.subprocess.run",
        return_value=completed,
    ):
        res = run_dagster_job(tmp_path)
    assert res.succeeded
    assert res.results_json_path == tmp_path / "results.json"


def test_run_dagster_job_raises_when_config_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="config.yaml"):
        run_dagster_job(tmp_path)
