"""Shared pytest fixtures: tmp_workspace creates an isolated workspace + cwd switch."""

import os
import shutil
from pathlib import Path
from typing import Iterator

import pytest


_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Iterator[Path]:
    """Phase 0 smoke fixture: copies iris.csv + config_smoke.yaml, chdirs."""
    shutil.copy(_FIXTURES / "iris.csv", tmp_path / "iris.csv")
    shutil.copy(_FIXTURES / "config_smoke.yaml", tmp_path / "config.yaml")
    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)


@pytest.fixture
def tmp_workspace_clustering(tmp_path: Path) -> Iterator[Path]:
    """Phase 1 fixture: clustering_with_kpi config on Iris."""
    shutil.copy(_FIXTURES / "iris.csv", tmp_path / "iris.csv")
    shutil.copy(_FIXTURES / "config_iris_clustering.yaml", tmp_path / "config.yaml")
    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)
