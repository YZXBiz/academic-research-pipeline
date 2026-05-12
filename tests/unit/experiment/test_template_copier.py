"""template_copier copies pipeline + examples but skips tests/venv/cache."""
from __future__ import annotations

from pathlib import Path

from academic_pipeline.experiment.template_copier import copy_template_into


def test_copy_includes_pipeline_and_pyproject(tmp_path: Path) -> None:
    copy_template_into(tmp_path)
    assert (tmp_path / "src" / "pipeline" / "definitions.py").exists()
    assert (tmp_path / "pyproject.toml").exists()
    assert (tmp_path / "examples" / "config_clustering_pharmacy.yaml").exists()


def test_copy_excludes_tests_and_caches(tmp_path: Path) -> None:
    copy_template_into(tmp_path)
    assert not (tmp_path / "tests").exists()
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "__pycache__").exists()
    assert not (tmp_path / "uv.lock").exists()
    assert not (tmp_path / ".dg").exists()
