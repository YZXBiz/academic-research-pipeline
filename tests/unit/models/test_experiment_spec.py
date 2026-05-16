"""Tests for the parameterized ExperimentSpec.

This replaces the old free-form `WorkspaceFiles` agent contract where
the agent generated arbitrary Python @asset modules. ExperimentSpec
is a strict typed schema: the agent picks values from enums + provides
dataset / target metadata. The workspace runs a pre-tested canonical
@asset chain against the spec, so the failure modes that haunted
run-0515 (dangling deps, ImportError, missing pip deps, wrong API
usage) cannot happen.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.models.experiment_spec import (
    Algorithm,
    CalibrationMethod,
    DatasetSource,
    ExperimentSpec,
    Metric,
)


def _valid_spec_kwargs() -> dict:
    """Minimal kwargs that build a valid spec — used as the baseline for negation tests."""
    return dict(
        dataset=DatasetSource(
            source="huggingface://rtweera/nhanes-diabetes-classified-training-dataset",
            files=["train.parquet"],
            entity_id_column="SEQN",
            target_column_patterns=["diabetes", "has_diabetes", "diabetes_binary"],
        ),
        algorithms=[Algorithm.LOGREG, Algorithm.AUTOGLUON],
        calibration_methods=[CalibrationMethod.NONE, CalibrationMethod.PLATT, CalibrationMethod.ISOTONIC],
        metrics=[Metric.AUC, Metric.BRIER, Metric.ECE],
        random_seed=42,
        time_limit_s=300,
    )


def test_minimal_spec_builds() -> None:
    """A spec with all required fields validates."""
    spec = ExperimentSpec(**_valid_spec_kwargs())
    assert spec.random_seed == 42
    assert Algorithm.LOGREG in spec.algorithms
    assert spec.time_limit_s == 300


def test_spec_is_frozen() -> None:
    """ExperimentSpec is immutable — protects against accidental mutation downstream."""
    spec = ExperimentSpec(**_valid_spec_kwargs())
    with pytest.raises(ValidationError):
        spec.random_seed = 99  # type: ignore[misc]


def test_random_seed_defaults_to_42() -> None:
    """Reproducibility default — agents don't have to specify it."""
    kw = _valid_spec_kwargs()
    del kw["random_seed"]
    spec = ExperimentSpec(**kw)
    assert spec.random_seed == 42


def test_time_limit_defaults_to_300s() -> None:
    """Per-AutoGluon-fit budget default. 300s is the rule-of-thumb medium_quality preset."""
    kw = _valid_spec_kwargs()
    del kw["time_limit_s"]
    spec = ExperimentSpec(**kw)
    assert spec.time_limit_s == 300


def test_algorithms_must_be_non_empty() -> None:
    """An experiment with zero algorithms is meaningless — reject at validation."""
    kw = _valid_spec_kwargs()
    kw["algorithms"] = []
    with pytest.raises(ValidationError):
        ExperimentSpec(**kw)


def test_metrics_must_be_non_empty() -> None:
    """An experiment with zero metrics has no observable output — reject."""
    kw = _valid_spec_kwargs()
    kw["metrics"] = []
    with pytest.raises(ValidationError):
        ExperimentSpec(**kw)


def test_calibration_methods_default_to_none_only() -> None:
    """If the agent doesn't ask for calibration, just run the raw model. Default to [NONE]."""
    kw = _valid_spec_kwargs()
    del kw["calibration_methods"]
    spec = ExperimentSpec(**kw)
    assert spec.calibration_methods == [CalibrationMethod.NONE]


def test_algorithm_enum_rejects_unknown_value() -> None:
    """The agent can ONLY pick algorithms the canonical @asset chain implements.
    String values outside the enum are rejected.
    """
    kw = _valid_spec_kwargs()
    with pytest.raises(ValidationError):
        ExperimentSpec(**{**kw, "algorithms": ["xgboost_custom_hyperparams"]})


def test_calibration_enum_rejects_unknown_value() -> None:
    """Same gate for calibration methods — restricts to NONE/PLATT/ISOTONIC."""
    kw = _valid_spec_kwargs()
    with pytest.raises(ValidationError):
        ExperimentSpec(**{**kw, "calibration_methods": ["temperature_scaling"]})


def test_metric_enum_rejects_unknown_value() -> None:
    """Same gate for metrics — restricts to AUC/BRIER/ECE/MCE."""
    kw = _valid_spec_kwargs()
    with pytest.raises(ValidationError):
        ExperimentSpec(**{**kw, "metrics": ["log_loss_custom"]})


def test_dataset_source_requires_at_least_one_file() -> None:
    """A dataset with no files is unusable."""
    with pytest.raises(ValidationError):
        DatasetSource(
            source="huggingface://x/y",
            files=[],
            entity_id_column="id",
            target_column_patterns=["target"],
        )


def test_dataset_source_requires_at_least_one_target_pattern() -> None:
    """At least one pattern must be present — the canonical module uses these to identify the target column at runtime."""
    with pytest.raises(ValidationError):
        DatasetSource(
            source="huggingface://x/y",
            files=["train.parquet"],
            entity_id_column="id",
            target_column_patterns=[],
        )


def test_random_seed_must_be_non_negative() -> None:
    """Negative random seeds are invalid in numpy/sklearn."""
    kw = _valid_spec_kwargs()
    with pytest.raises(ValidationError):
        ExperimentSpec(**{**kw, "random_seed": -1})


def test_time_limit_must_be_positive() -> None:
    """A 0-second budget can't fit AutoGluon — reject."""
    kw = _valid_spec_kwargs()
    with pytest.raises(ValidationError):
        ExperimentSpec(**{**kw, "time_limit_s": 0})


def test_spec_round_trips_json() -> None:
    """The agent will emit JSON; we parse it. Round-trip must preserve all fields."""
    spec = ExperimentSpec(**_valid_spec_kwargs())
    js = spec.model_dump_json()
    restored = ExperimentSpec.model_validate_json(js)
    assert restored == spec


def test_algorithms_dedupe_preserves_order() -> None:
    """If the agent repeats an algorithm in the list, dedupe but preserve order."""
    kw = _valid_spec_kwargs()
    kw["algorithms"] = [Algorithm.LOGREG, Algorithm.AUTOGLUON, Algorithm.LOGREG, Algorithm.DUMMY]
    spec = ExperimentSpec(**kw)
    assert spec.algorithms == [Algorithm.LOGREG, Algorithm.AUTOGLUON, Algorithm.DUMMY]
