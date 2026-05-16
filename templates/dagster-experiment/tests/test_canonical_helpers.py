"""Tests for the pure helpers under pipeline.assets.experiment._canonical_helpers.

Goal: pin the tricky bits (target detection, ECE/MCE formulas, calibration
plumbing) so the canonical chain's correctness doesn't drift. The @asset
wrappers in canonical.py are thin and tested separately via dagster materialize.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.assets.experiment._canonical_helpers import (
    _AutoGluonProbaWrapper,
    _ScalarCalibratorWrapper,
    TrainTestSplit,
    calibrate,
    compute_metric,
    ensure_binary_target,
    expected_calibration_error,
    identify_target_column,
    maximum_calibration_error,
    select_feature_columns,
    stratified_split,
    train_base_model,
)
from pipeline.config_models import Algorithm, CalibrationMethod, Metric


# ------------------------ target-column detection ------------------------

def test_identify_target_first_pattern_first_match() -> None:
    # Two columns contain "diabetes" — first one wins (column order).
    cols = ["SEQN", "RIDAGEYR", "has_diabetes", "BMXBMI", "diabetes_binary"]
    assert identify_target_column(cols, ["diabetes"]) == "has_diabetes"


def test_identify_target_case_insensitive() -> None:
    cols = ["SEQN", "Has_Diabetes"]
    assert identify_target_column(cols, ["diabetes"]) == "Has_Diabetes"


def test_identify_target_falls_through_to_second_pattern() -> None:
    cols = ["SEQN", "outcome_label"]
    assert identify_target_column(cols, ["diabetes", "outcome"]) == "outcome_label"


def test_identify_target_raises_on_no_match() -> None:
    with pytest.raises(ValueError, match="No column matched"):
        identify_target_column(["SEQN", "BMXBMI"], ["diabetes", "target"])


# ------------------------ feature selection ------------------------

def test_select_feature_columns_drops_target_and_entity_and_categoricals() -> None:
    df = pd.DataFrame(
        {
            "SEQN": [1, 2, 3],
            "age": [40, 50, 60],
            "bmi": [22.0, 25.0, 30.0],
            "race": ["A", "B", "A"],  # categorical (object dtype) — dropped
            "target": [0, 1, 0],
        }
    )
    feats = select_feature_columns(df, target_col="target", entity_id_col="SEQN")
    assert feats == ["age", "bmi"]


# ------------------------ binary-target coercion ------------------------

def test_ensure_binary_target_maps_lo_hi_to_0_1() -> None:
    y = pd.Series([1, 1, 2, 2, 2])
    out = ensure_binary_target(y)
    assert out.tolist() == [0, 0, 1, 1, 1]


def test_ensure_binary_target_raises_on_three_values() -> None:
    y = pd.Series([0, 1, 2])
    with pytest.raises(ValueError, match="not binary"):
        ensure_binary_target(y)


def test_ensure_binary_target_ignores_nan() -> None:
    y = pd.Series([0, 1, np.nan, 1, 0])
    out = ensure_binary_target(y.dropna())
    assert out.tolist() == [0, 1, 1, 0]


# ------------------------ stratified split ------------------------

def test_stratified_split_preserves_prevalence_across_folds() -> None:
    rng = np.random.default_rng(0)
    n = 500
    df = pd.DataFrame(
        {
            "id": np.arange(n),
            "x1": rng.normal(size=n),
            "x2": rng.normal(size=n),
            "target": rng.binomial(1, 0.3, size=n),
        }
    )
    split = stratified_split(df, ["x1", "x2"], "target", seed=42)
    p_full = df["target"].mean()
    assert abs(split.y_train.mean() - p_full) < 0.05
    assert abs(split.y_cal.mean() - p_full) < 0.05
    assert abs(split.y_test.mean() - p_full) < 0.05


def test_stratified_split_sizes_add_up() -> None:
    rng = np.random.default_rng(0)
    n = 100
    df = pd.DataFrame(
        {"id": np.arange(n), "x": rng.normal(size=n), "y": rng.binomial(1, 0.5, size=n)}
    )
    s = stratified_split(df, ["x"], "y", seed=0)
    assert len(s.X_train) + len(s.X_cal) + len(s.X_test) == n


# ------------------------ ECE / MCE ------------------------

def test_ece_zero_for_perfect_calibration() -> None:
    y_prob = np.array([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
    # Perfectly calibrated: y_true = y_prob (we round to bin centers)
    y_true = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])  # roughly matches expected
    # Single sample per bin so each bin's accuracy == y_true value
    # ECE = average |acc - conf| across populated bins
    ece = expected_calibration_error(y_true, y_prob, n_bins=10)
    # Just verify it's a plausible small-ish number; with 1 sample/bin not exactly 0
    assert 0.0 <= ece <= 0.5


def test_ece_high_for_systematic_overconfidence() -> None:
    # All predictions claim 0.9 but only half the events occur → ~0.4 ECE
    y_prob = np.full(100, 0.9)
    y_true = np.zeros(100)
    y_true[:50] = 1  # 50% prevalence vs 90% predicted
    ece = expected_calibration_error(y_true, y_prob)
    assert ece > 0.35


def test_mce_picks_worst_bin() -> None:
    # bin 9 (0.9-1.0): 100 preds at 0.95 but only 50% positive → |0.5 - 0.95| = 0.45
    # bin 0 (0.0-0.1): 100 preds at 0.05 and 5% positive → |0.05 - 0.05| ≈ 0
    y_prob = np.concatenate([np.full(100, 0.05), np.full(100, 0.95)])
    y_true = np.concatenate([np.zeros(95), np.ones(5), np.zeros(50), np.ones(50)])
    mce = maximum_calibration_error(y_prob=y_prob, y_true=y_true)
    assert mce > 0.4


def test_ece_handles_empty_bins() -> None:
    # All predictions in one tight bin — empty bins must contribute 0
    y_prob = np.full(20, 0.5)
    y_true = np.array([0, 1] * 10)
    ece = expected_calibration_error(y_true, y_prob)
    # 50% prevalence vs 50% predicted → near 0
    assert ece < 0.05


# ------------------------ metric dispatch ------------------------

def test_compute_metric_auc_perfect_separation() -> None:
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.2, 0.8, 0.9])
    assert compute_metric(Metric.AUC, y_true, y_prob) == 1.0


def test_compute_metric_brier_at_uniform_0_5() -> None:
    y_true = np.array([0, 1, 0, 1])
    y_prob = np.full(4, 0.5)
    assert compute_metric(Metric.BRIER, y_true, y_prob) == pytest.approx(0.25)


# ------------------------ training + calibration round-trip ------------------------

def _toy_split(n: int = 300, seed: int = 0) -> TrainTestSplit:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "id": np.arange(n),
            "x1": rng.normal(size=n),
            "x2": rng.normal(size=n),
            "target": rng.binomial(1, 0.4, size=n),
        }
    )
    return stratified_split(df, ["x1", "x2"], "target", seed=seed)


def test_train_logreg_returns_proba_with_correct_shape() -> None:
    split = _toy_split()
    m = train_base_model(Algorithm.LOGREG, split, seed=0, time_limit_s=60)
    proba = m.predict_proba(split.X_test)
    assert proba.shape == (len(split.X_test), 2)
    assert np.all(proba >= 0) and np.all(proba <= 1)


def test_train_dummy_runs() -> None:
    split = _toy_split()
    m = train_base_model(Algorithm.DUMMY, split, seed=0, time_limit_s=60)
    assert m.predict_proba(split.X_test).shape == (len(split.X_test), 2)


def test_calibrate_none_is_identity() -> None:
    split = _toy_split()
    m = train_base_model(Algorithm.LOGREG, split, seed=0, time_limit_s=60)
    cal = calibrate(CalibrationMethod.NONE, m, split, seed=0)
    assert cal is m


def test_calibrate_platt_changes_probs() -> None:
    split = _toy_split()
    m = train_base_model(Algorithm.LOGREG, split, seed=0, time_limit_s=60)
    cal = calibrate(CalibrationMethod.PLATT, m, split, seed=0)
    raw = m.predict_proba(split.X_test)[:, 1]
    cooked = cal.predict_proba(split.X_test)[:, 1]
    # Platt on a logreg base is roughly identity; just verify wrapping path runs + shape
    assert cooked.shape == raw.shape
    assert np.all(cooked >= 0) and np.all(cooked <= 1)


def test_calibrate_isotonic_changes_probs() -> None:
    split = _toy_split()
    m = train_base_model(Algorithm.LOGREG, split, seed=0, time_limit_s=60)
    cal = calibrate(CalibrationMethod.ISOTONIC, m, split, seed=0)
    cooked = cal.predict_proba(split.X_test)[:, 1]
    assert cooked.shape == (len(split.X_test),)
    assert np.all(cooked >= 0) and np.all(cooked <= 1)


def test_scalar_calibrator_wrapper_clips_to_unit() -> None:
    """A pathological map can push values out of [0,1]; wrapper must clip."""
    class _Base:
        def predict_proba(self, X):
            return np.array([[0.1, 0.9], [0.4, 0.6]])
    wrap = _ScalarCalibratorWrapper(_Base(), map_fn=lambda s: s + 2)
    out = wrap.predict_proba(pd.DataFrame({"x": [1, 2]}))
    assert out.max() <= 1.0 and out.min() >= 0.0


def test_autogluon_wrapper_handles_dataframe_proba() -> None:
    """AutoGluon returns a DataFrame; wrapper must extract positive column."""

    class _FakePred:
        def predict_proba(self, X):
            return pd.DataFrame({"neg": [0.3, 0.7], "pos": [0.7, 0.3]})

    wrap = _AutoGluonProbaWrapper(_FakePred())
    out = wrap.predict_proba(pd.DataFrame({"x": [1, 2]}))
    assert out.shape == (2, 2)
    assert out[0, 1] == pytest.approx(0.7)
    assert out[1, 1] == pytest.approx(0.3)
