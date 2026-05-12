"""Frozen Pydantic schema for workspace/config.yaml.

Orchestration-only. The agent generates BOTH this config AND the per-experiment
@asset modules under pipeline.assets.experiment — algorithms / metrics / KPIs
are encoded in the generated code, not pinned to enums here. This file only
captures what the FIXED scaffold needs to know: where the data lives, what
identifies a row, where to log, and the random seed.

Anything an experiment-specific @asset needs (algorithm names, k grids,
metrics, AutoGluon presets, custom hyperparams) goes inside the generated
asset module — not here. This keeps the contract tight: the agent can pivot
to any algorithm, library, or methodology without changing the schema.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatasetConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str = Field(description="huggingface://org/repo, file://path, or http(s)://url")
    files: list[str] = Field(description="filenames inside the source")
    entity_id_column: str = Field(description="row-identity column; never used as a feature")
    date_column: str | None = None


class MLflowConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    experiment_name: str = "experiment"
    tags: dict[str, str] = Field(default_factory=dict)


class ReproducibilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    random_seed: int = 42


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1
    dataset: DatasetConfig
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    reproducibility: ReproducibilityConfig = Field(default_factory=ReproducibilityConfig)
