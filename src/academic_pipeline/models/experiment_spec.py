"""Typed specification the config_writer agent fills in lieu of generating code.

The pre-2026-05-15 design had the agent emit free-form Python @asset
modules. Every run of run-0515 exposed a new failure mode: dangling
deps, wrong import paths, missing pip packages, wrong column names.
This is the new contract: the agent picks from enums + provides
dataset metadata, and the workspace runs a pre-tested canonical
@asset chain. No agent codegen, no codegen-class failures.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Algorithm(StrEnum):
    """Algorithms the canonical @asset chain implements."""

    DUMMY = "dummy"
    LOGREG = "logreg"
    AUTOGLUON = "autogluon"


class CalibrationMethod(StrEnum):
    """Post-hoc probability calibration techniques supported by the canonical chain."""

    NONE = "none"
    PLATT = "platt"
    ISOTONIC = "isotonic"


class Metric(StrEnum):
    """Evaluation metrics computed for each (algorithm, calibration) combo."""

    AUC = "auc"
    BRIER = "brier"
    ECE = "ece"
    MCE = "mce"


class DatasetSource(BaseModel):
    """How the canonical chain locates the dataset and its target column."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(description="huggingface://org/repo or file://path or http(s)://url")
    files: list[str] = Field(min_length=1, description="One or more data files; each becomes a `raw_<stem>` DuckDB table")
    entity_id_column: str = Field(description="Row-identity column; never used as a feature")
    target_column_patterns: list[str] = Field(
        min_length=1,
        description=(
            "Case-insensitive substrings searched in column names to identify the target. "
            "First match wins. Example: ['diabetes', 'has_diabetes', 'diabetes_binary']."
        ),
    )


class ExperimentSpec(BaseModel):
    """Closed-form description of one benchmark-comparison experiment.

    The config_writer agent's entire job is to fill this. No Python.
    """

    model_config = ConfigDict(frozen=True)

    dataset: DatasetSource
    algorithms: list[Algorithm] = Field(
        min_length=1,
        description="Algorithms to train. Order is preserved; duplicates are removed.",
    )
    calibration_methods: list[CalibrationMethod] = Field(
        default_factory=lambda: [CalibrationMethod.NONE],
        description=(
            "Calibration methods to apply per algorithm. CalibrationMethod.NONE = raw model. "
            "If omitted, defaults to [NONE] (no calibration)."
        ),
    )
    metrics: list[Metric] = Field(
        min_length=1,
        description="Evaluation metrics to compute on the held-out test set.",
    )
    random_seed: int = Field(default=42, ge=0, description="Seed for all stochastic steps. Default 42.")
    time_limit_s: int = Field(
        default=300,
        gt=0,
        description="Per-AutoGluon-fit budget in seconds (only consumed when AUTOGLUON in algorithms).",
    )

    @field_validator("algorithms", mode="after")
    @classmethod
    def _dedupe_algorithms_preserving_order(cls, v: list[Algorithm]) -> list[Algorithm]:
        seen: set[Algorithm] = set()
        return [x for x in v if not (x in seen or seen.add(x))]
