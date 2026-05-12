"""Contract tests: verify ExperimentResults parses real ML agent output.

These tests use realistic results.json structures produced by the ML agent
inside Docker. If the agent's output format changes or the Pydantic model
drifts, these tests catch it before a 90-minute pipeline run does.
"""
from __future__ import annotations

import pytest

from academic_pipeline.models.experiment import (
    ExperimentResults,
    MultiSeedMetric,
)


REAL_MULTI_SEED_RESULTS = {
    "experiment": "AutoGluon vs Conventional Models",
    "dataset": {"name": "diabetes-readmission", "source": "huggingface"},
    "seeds": [42, 123, 456],
    "methods": ["DummyClassifier", "LogisticRegression", "RandomForest", "AutoGluon"],
    "metrics": {
        "DummyClassifier": {
            "roc_auc": {"mean": 0.5, "std": 0.0, "values": [0.5, 0.5, 0.5]},
            "balanced_accuracy": {"mean": 0.5, "std": 0.0, "values": [0.5, 0.5, 0.5]},
            "f1_weighted": {"mean": 0.378, "std": 0.0, "values": [0.378, 0.378, 0.378]},
        },
        "LogisticRegression": {
            "roc_auc": {"mean": 0.659, "std": 0.010, "values": [0.660, 0.671, 0.647]},
            "balanced_accuracy": {"mean": 0.606, "std": 0.011, "values": [0.611, 0.616, 0.591]},
        },
        "AutoGluon": {
            "roc_auc": {"mean": 0.679, "std": 0.005, "values": [0.680, 0.679, 0.678]},
            "balanced_accuracy": {"mean": 0.620, "std": 0.010, "values": [0.630, 0.620, 0.610]},
            "brier_score": {"mean": 0.225, "std": 0.002, "values": [0.224, 0.225, 0.226]},
        },
    },
    "statistical_tests": {
        "AutoGluon_vs_DummyClassifier": {
            "test_name": "Wilcoxon signed-rank (one-sided, greater)",
            "statistic": 6.0,
            "p_value": 0.125,
            "bonferroni_alpha": 0.017,
            "significant_bonferroni": False,
            "significant_nominal": False,
            "mean_auroc_difference": 0.179,
        },
        "AutoGluon_vs_LogisticRegression": {
            "test_name": "Wilcoxon signed-rank (one-sided, greater)",
            "statistic": 6.0,
            "p_value": 0.125,
            "significant_nominal": False,
        },
    },
    "success_criteria": {"auroc_improvement_threshold": 0.02},
    "figures": [
        "calibration_curve.png",
        "confusion_matrix.png",
        "roc_curve.png",
        "shap_summary.png",
        "performance_bar_chart.png",
    ],
    "leaderboard_top10": [
        {"model": "LightGBM", "score_test": 0.672},
        {"model": "CatBoost", "score_test": 0.670},
    ],
}

FLAT_METRIC_RESULTS = {
    "success": True,
    "metrics": {
        "AutoGluon": {"accuracy": 0.85, "f1": 0.82},
        "LogisticRegression": {"accuracy": 0.78, "f1": 0.74},
    },
}


def test_parses_multi_seed_results():
    """Real ML agent output with {mean, std, values} per metric."""
    r = ExperimentResults.model_validate(REAL_MULTI_SEED_RESULTS)
    assert "AutoGluon" in r.metrics
    roc = r.metrics["AutoGluon"]["roc_auc"]
    assert isinstance(roc, MultiSeedMetric)
    assert roc.mean == pytest.approx(0.679)
    assert roc.std == pytest.approx(0.005)
    assert len(roc.values) == 3


def test_parses_flat_metric_results():
    """Simple dict[str, float] metrics still work."""
    r = ExperimentResults.model_validate(FLAT_METRIC_RESULTS)
    assert r.metrics["AutoGluon"]["accuracy"] == 0.85


def test_success_defaults_true():
    """success field defaults to True when omitted (ML agent doesn't always set it)."""
    r = ExperimentResults.model_validate(REAL_MULTI_SEED_RESULTS)
    assert r.success is True


def test_statistical_tests_accept_raw_dicts():
    """Statistical tests from ML agent have extra fields beyond StatisticalTest."""
    r = ExperimentResults.model_validate(REAL_MULTI_SEED_RESULTS)
    assert len(r.statistical_tests) == 2
    test = r.statistical_tests["AutoGluon_vs_DummyClassifier"]
    assert isinstance(test, dict)
    assert test["p_value"] == 0.125


def test_figures_accept_plain_strings():
    """ML agent returns figure filenames as strings, not FigureArtifact objects."""
    r = ExperimentResults.model_validate(REAL_MULTI_SEED_RESULTS)
    assert len(r.figures) == 5
    assert "roc_curve.png" in r.figures


def test_extra_fields_allowed():
    """ML agent adds fields like experiment, dataset, leaderboard_top10."""
    r = ExperimentResults.model_validate(REAL_MULTI_SEED_RESULTS)
    assert r.model_extra is not None
    assert "leaderboard_top10" in r.model_extra
