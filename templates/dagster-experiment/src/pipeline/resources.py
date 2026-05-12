"""Workspace resources: DuckDB + ConfigResource + MLflowResource."""
from __future__ import annotations

from pathlib import Path

import mlflow as _mlflow
import yaml
from dagster import ConfigurableResource
from dagster_duckdb import DuckDBResource
from pydantic import PrivateAttr

from pipeline.config_models import ExperimentConfig


def workspace_dir() -> Path:
    """The Dagster process is launched with cwd = workspace/.

    Resources resolve paths against this. Helpers below stay pure (no globals)."""
    return Path.cwd()


class ConfigResource(ConfigurableResource):
    """Loads workspace/config.yaml once, caches the parsed ExperimentConfig.

    Assets depend on this resource and read `cfg = config.get()`."""
    config_path: str = "config.yaml"

    _cached: ExperimentConfig | None = PrivateAttr(default=None)

    def get(self) -> ExperimentConfig:
        if self._cached is None:
            path = workspace_dir() / self.config_path
            data = yaml.safe_load(path.read_text())
            self._cached = ExperimentConfig.model_validate(data)
        return self._cached


def make_duckdb_resource() -> DuckDBResource:
    """workspace/experiment.duckdb is the single store for all materializations."""
    return DuckDBResource(database=str(workspace_dir() / "experiment.duckdb"))


def _make_mlflow_uri() -> str:
    """File-backed MLflow store inside workspace/mlruns/."""
    p = workspace_dir() / "mlruns"
    p.mkdir(parents=True, exist_ok=True)
    return f"file://{p.resolve()}"


class MLflowResource(ConfigurableResource):
    """Lightweight wrapper. Each asset opens nested runs via `mlflow.start_run(nested=True)`.

    Configures tracking URI + experiment on first .client() call. Idempotent."""

    experiment_name: str = "experiment"

    _configured: bool = PrivateAttr(default=False)

    def client(self):
        if not self._configured:
            _mlflow.set_tracking_uri(_make_mlflow_uri())
            _mlflow.set_experiment(self.experiment_name)
            self._configured = True
        return _mlflow
