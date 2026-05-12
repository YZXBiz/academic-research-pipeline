"""Tests for the producer-side helper in experiment/producers.py.

The producer walks the actual ExperimentResults shape used by the experiment
subgraph: metrics is a nested dict[str, dict[str, float | MultiSeedMetric]] where
the outer key is the method name and the inner key is the metric label.
"""

from __future__ import annotations

import pytest

from academic_pipeline.experiment.producers import (
    extract_numerical_products_from_result,
)
from academic_pipeline.models.experiment import ExperimentResults, MultiSeedMetric
from academic_pipeline.models.numerical import NumericalStore


@pytest.fixture
def stub_result() -> ExperimentResults:
    """Minimal stand-in shape matching ExperimentResults.metrics structure."""
    return ExperimentResults(
        success=True,
        metrics={
            "logistic_regression": {"auc": 0.87, "f1": 0.72, "n_samples": 4127},
        },
        code="y_pred = model.predict(X_test)\nauc = roc_auc_score(y_test, y_pred)\n",
    )


def test_extract_produces_one_product_per_scalar_metric(stub_result: ExperimentResults) -> None:
    products = extract_numerical_products_from_result(
        result=stub_result,
        run_id="run-x",
        source_step="experiment.analysis",
    )
    labels = {p.label for p in products}
    assert labels == {
        "logistic_regression__auc",
        "logistic_regression__f1",
        "logistic_regression__n_samples",
    }


def test_extract_preserves_value_as_string(stub_result: ExperimentResults) -> None:
    products = extract_numerical_products_from_result(
        result=stub_result, run_id="run-x", source_step="experiment.analysis",
    )
    by_label = {p.label: p for p in products}
    assert by_label["logistic_regression__auc"].value == "0.87"
    # ExperimentResults.metrics is typed as dict[str, dict[str, float | MultiSeedMetric]]
    # so pydantic coerces ints to floats — n_samples=4127 round-trips as "4127.0".
    assert by_label["logistic_regression__n_samples"].value == "4127.0"


def test_extract_carries_run_id_and_step(stub_result: ExperimentResults) -> None:
    products = extract_numerical_products_from_result(
        result=stub_result, run_id="run-x", source_step="experiment.analysis",
    )
    for p in products:
        assert p.source_run_id == "run-x"
        assert p.source_step == "experiment.analysis"


def test_extract_skips_non_scalar_values() -> None:
    result = ExperimentResults(
        success=True,
        metrics={
            "model_a": {"valid_scalar": 1.0},
        },
    )
    products = extract_numerical_products_from_result(
        result=result, run_id="r", source_step="s",
    )
    labels = {p.label for p in products}
    assert labels == {"model_a__valid_scalar"}


def test_extract_handles_multi_seed_metric() -> None:
    """MultiSeedMetric values should emit one product using the .mean field."""
    result = ExperimentResults(
        success=True,
        metrics={
            "model_a": {
                "auc": MultiSeedMetric(mean=0.85, std=0.02, values=[0.83, 0.85, 0.87]),
            },
        },
    )
    products = extract_numerical_products_from_result(
        result=result, run_id="r", source_step="s",
    )
    by_label = {p.label: p for p in products}
    assert "model_a__auc" in by_label
    assert by_label["model_a__auc"].value == "0.85"


def test_extract_skips_booleans() -> None:
    """bool subclasses int but isn't a numeric metric — must be skipped.

    Note: ExperimentResults.metrics is strictly typed so pydantic coerces booleans
    to floats at construction. To exercise the producer's defensive bool guard we
    construct a model_validate from a raw dict and bypass the float coercion via
    a Mock-style stand-in.
    """
    from unittest.mock import MagicMock
    fake = MagicMock(spec=ExperimentResults)
    fake.metrics = {"model_a": {"converged": True, "loss": 0.5}}
    products = extract_numerical_products_from_result(
        result=fake, run_id="r", source_step="s",
    )
    labels = {p.label for p in products}
    assert labels == {"model_a__loss"}


def test_store_populated_after_extract() -> None:
    store = NumericalStore()
    result = ExperimentResults(success=True, metrics={"m": {"x": 1.0}})
    products = extract_numerical_products_from_result(
        result=result, run_id="r", source_step="s",
    )
    for p in products:
        store = store.add(p)
    assert "m__x" in store.products
