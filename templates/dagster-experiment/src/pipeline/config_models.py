"""Frozen Pydantic schema for workspace/config.yaml.

Post-2026-05-15: replaced free-form agent @asset codegen with a
parameterized canonical chain. The agent no longer generates Python;
it fills `ExperimentSpec` (typed enums + dataset metadata) and the
template-shipped `pipeline.assets.experiment.canonical` module runs
the chain against the spec. Loses the "agent can pivot to any
algorithm" freedom; gains 100% reliability for the
benchmark-comparison common case. Other experiment types
(clustering, timeseries) would each get their own canonical module.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str = Field(description="huggingface://org/repo, file://path, or http(s)://url")
    files: list[str] = Field(description="filenames inside the source")
    entity_id_column: str = Field(description="row-identity column; never used as a feature")
    date_column: str | None = None
    target_column_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Case-insensitive substrings searched in column names to identify "
            "the binary target. First match wins. Used only by the canonical "
            "benchmark-comparison chain."
        ),
    )


class MLflowConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    experiment_name: str = "experiment"
    tags: dict[str, str] = Field(default_factory=dict)


class ReproducibilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    random_seed: int = 42


class Algorithm(StrEnum):
    """Algorithms the canonical chain implements. Must stay in sync with
    academic_pipeline.models.experiment_spec.Algorithm (parent-side mirror)."""

    DUMMY = "dummy"
    LOGREG = "logreg"
    AUTOGLUON = "autogluon"


class CalibrationMethod(StrEnum):
    """Post-hoc probability calibration methods. Must stay in sync with parent-side."""

    NONE = "none"
    PLATT = "platt"
    ISOTONIC = "isotonic"


class Metric(StrEnum):
    """Evaluation metrics. Must stay in sync with parent-side."""

    AUC = "auc"
    BRIER = "brier"
    ECE = "ece"
    MCE = "mce"


class ExperimentSpec(BaseModel):
    """Closed-form description of one benchmark-comparison experiment.

    Mirrors academic_pipeline.models.experiment_spec.ExperimentSpec. The
    agent emits JSON that conforms to that parent-side class; the workspace
    reads it via this class. Keep schemas identical.
    """

    model_config = ConfigDict(frozen=True)

    algorithms: list[Algorithm] = Field(min_length=1)
    calibration_methods: list[CalibrationMethod] = Field(
        default_factory=lambda: [CalibrationMethod.NONE]
    )
    metrics: list[Metric] = Field(min_length=1)
    random_seed: int = Field(default=42, ge=0)
    time_limit_s: int = Field(default=300, gt=0)

    @field_validator("algorithms", mode="after")
    @classmethod
    def _dedupe(cls, v: list[Algorithm]) -> list[Algorithm]:
        seen: set[Algorithm] = set()
        return [x for x in v if not (x in seen or seen.add(x))]


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1] = 1
    dataset: DatasetConfig
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    reproducibility: ReproducibilityConfig = Field(default_factory=ReproducibilityConfig)
    experiment_spec: ExperimentSpec | None = Field(
        default=None,
        description=(
            "Parameterized spec for the canonical benchmark-comparison chain. "
            "Required when using `pipeline.assets.experiment.canonical`. Left "
            "None for legacy free-codegen experiments (deprecated)."
        ),
    )
