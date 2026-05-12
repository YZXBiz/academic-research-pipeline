"""ExperimentConfig schema is orchestration-only — no algorithm/metric enums."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.config_models import ExperimentConfig


_GOOD = {
    "schema_version": 1,
    "dataset": {
        "source": "huggingface://t4tiana/store-sales-time-series-forecasting",
        "files": ["train.csv", "stores.csv"],
        "entity_id_column": "store_nbr",
    },
    "mlflow": {"experiment_name": "store_segmentation"},
    "reproducibility": {"random_seed": 42},
}


def test_minimal_config_validates() -> None:
    cfg = ExperimentConfig.model_validate(_GOOD)
    assert cfg.dataset.entity_id_column == "store_nbr"
    assert cfg.mlflow.experiment_name == "store_segmentation"
    assert cfg.reproducibility.random_seed == 42


def test_mlflow_and_reproducibility_default() -> None:
    """Both blocks have defaults — only dataset is required."""
    minimal = {
        "schema_version": 1,
        "dataset": {
            "source": "file:///tmp/data",
            "files": ["x.csv"],
            "entity_id_column": "id",
        },
    }
    cfg = ExperimentConfig.model_validate(minimal)
    assert cfg.mlflow.experiment_name == "experiment"
    assert cfg.reproducibility.random_seed == 42


def test_dataset_required() -> None:
    bad = {"schema_version": 1}
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(bad)


def test_no_algorithm_field_in_schema() -> None:
    """Algorithms / metrics / k-grids belong in generated @asset code, not config.

    If a future change accidentally re-adds an algorithm enum to the schema,
    this test fires — that means the open-ended-ML pivot has regressed.
    """
    fields = ExperimentConfig.model_fields.keys()
    forbidden = {"problem", "feature_engineering", "clustering", "kpi"}
    leaked = forbidden & set(fields)
    assert not leaked, (
        f"Schema must stay orchestration-only. Found leaked algorithm fields: {leaked}. "
        "These belong in generated assets/experiment/*.py modules, not config_models.py."
    )
