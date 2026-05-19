"""Pure helpers backing pipeline.assets.experiment.canonical.

Lives in an underscored module so the Dagster auto-loader skips it
(no @asset here). Imported by canonical.py. Kept separate so the
chain's tricky bits (target-column detection, calibration plumbing,
metric formulas) are unit-testable without standing up Dagster.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from pipeline.config_models import Algorithm, CalibrationMethod, Metric


def identify_target_column(columns: list[str], patterns: list[str]) -> str:
    """Return the first column whose name contains any pattern (case-insensitive).

    Raises ValueError if nothing matches — the canonical chain has nothing
    to predict and must fail loudly so AbortNode trips.
    """
    for pat in patterns:
        pat_lower = pat.lower()
        for col in columns:
            if pat_lower in col.lower():
                return col
    raise ValueError(
        f"No column matched any target pattern. Patterns: {patterns}. "
        f"Available columns: {columns[:20]}{'...' if len(columns) > 20 else ''}"
    )


def select_feature_columns(
    df: pd.DataFrame, target_col: str, entity_id_col: str
) -> list[str]:
    """Numeric columns minus target + entity_id. Categoricals are dropped here —
    the canonical chain stays simple. AutoGluon handles its own preprocessing
    if AUTOGLUON is in the spec.
    """
    return [
        c
        for c in df.columns
        if c not in {target_col, entity_id_col} and np.issubdtype(df[c].dtype, np.number)
    ]


def ensure_binary_target(y: pd.Series) -> pd.Series:
    """Coerce target to {0, 1}. If already 2 unique values, map smaller → 0,
    larger → 1. Otherwise raise.
    """
    unique = pd.unique(y.dropna())
    if len(unique) != 2:
        raise ValueError(
            f"Target column is not binary: found {len(unique)} unique values: {unique[:5]}"
        )
    a, b = sorted(unique)
    return y.map({a: 0, b: 1}).astype(int)


@dataclass(frozen=True)
class TrainTestSplit:
    X_train: pd.DataFrame
    X_cal: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_cal: pd.Series
    y_test: pd.Series


def stratified_split(
    df: pd.DataFrame, feature_cols: list[str], target_col: str, seed: int
) -> TrainTestSplit:
    """80/20 train+cal vs test, then 80/20 train vs cal — stratified on the
    target so all three splits have the same positive prevalence.
    """
    df = df.dropna(subset=[target_col])
    X = df[feature_cols].copy()
    # NHANES (and most real tabular data) has NaN in feature columns. sklearn
    # LogisticRegression and DummyClassifier raise ValueError on NaN by
    # default. Impute with per-column median fitted on the WHOLE pre-split
    # frame — this is a mild data-leak (medians cross train/test) but the
    # alternative (dropping NaN rows) typically loses >50% of NHANES rows.
    # Median imputation is the standard NHANES-modeling preprocessing step.
    X = X.fillna(X.median(numeric_only=True))
    # Any feature columns that are still all-NaN (no median) get dropped.
    all_nan = [c for c in X.columns if X[c].isna().all()]
    if all_nan:
        X = X.drop(columns=all_nan)
    y = ensure_binary_target(df[target_col])
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )
    X_train, X_cal, y_train, y_cal = train_test_split(
        X_trainval, y_trainval, test_size=0.2, random_state=seed, stratify=y_trainval
    )
    return TrainTestSplit(
        X_train=X_train,
        X_cal=X_cal,
        X_test=X_test,
        y_train=y_train,
        y_cal=y_cal,
        y_test=y_test,
    )


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """ECE with equal-width bins.

    Standard formula: sum over bins of (bin_size / total) * |bin_accuracy - bin_confidence|.
    Empty bins contribute 0.
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(y_prob, bins) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)
    total = 0.0
    n = len(y_true)
    for k in range(n_bins):
        mask = bin_idx == k
        if not mask.any():
            continue
        bin_acc = float(y_true[mask].mean())
        bin_conf = float(y_prob[mask].mean())
        bin_weight = mask.sum() / n
        total += bin_weight * abs(bin_acc - bin_conf)
    return total


def maximum_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """MCE — worst-case bin miscalibration. Useful for spotting one bad bin
    that ECE hides via averaging."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(y_prob, bins) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)
    worst = 0.0
    for k in range(n_bins):
        mask = bin_idx == k
        if not mask.any():
            continue
        bin_acc = float(y_true[mask].mean())
        bin_conf = float(y_prob[mask].mean())
        worst = max(worst, abs(bin_acc - bin_conf))
    return worst


def compute_metric(name: Metric, y_true: np.ndarray, y_prob: np.ndarray) -> float:
    if name == Metric.AUC:
        return float(roc_auc_score(y_true, y_prob))
    if name == Metric.BRIER:
        return float(brier_score_loss(y_true, y_prob))
    if name == Metric.ECE:
        return expected_calibration_error(y_true, y_prob)
    if name == Metric.MCE:
        return maximum_calibration_error(y_true, y_prob)
    raise ValueError(f"Unknown metric: {name}")


def train_base_model(algo: Algorithm, split: TrainTestSplit, seed: int, time_limit_s: int) -> Any:
    """Train one base model on (X_train, y_train). Returns a fitted object
    with a `predict_proba` method whose [:, 1] is the positive-class score.
    """
    if algo == Algorithm.DUMMY:
        m = DummyClassifier(strategy="stratified", random_state=seed)
        m.fit(split.X_train, split.y_train)
        return m
    if algo == Algorithm.LOGREG:
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=seed))
        m.fit(split.X_train, split.y_train)
        return m
    if algo == Algorithm.AUTOGLUON:
        from autogluon.tabular import TabularPredictor

        train_df = split.X_train.copy()
        train_df["__y__"] = split.y_train.values
        pred = TabularPredictor(
            label="__y__",
            problem_type="binary",
            eval_metric="roc_auc",
            verbosity=0,
        )
        pred.fit(train_data=train_df, presets="medium_quality", time_limit=time_limit_s)
        return _AutoGluonProbaWrapper(pred)
    raise ValueError(f"Unknown algorithm: {algo}")


@dataclass
class _AutoGluonProbaWrapper:
    """Give AutoGluon a predict_proba shape matching sklearn (returns (n, 2)
    array of [neg_proba, pos_proba])."""

    pred: Any

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.pred.predict_proba(X)
        if isinstance(proba, pd.DataFrame):
            pos = proba.iloc[:, -1].to_numpy()
        else:
            pos = np.asarray(proba)[:, -1]
        return np.stack([1.0 - pos, pos], axis=1)


def calibrate(
    method: CalibrationMethod,
    model: Any,
    split: TrainTestSplit,
    seed: int,
) -> Any:
    """Wrap `model` with a post-hoc calibrator fit on (X_cal, y_cal). Returns
    a new object whose predict_proba returns calibrated probabilities.
    """
    if method == CalibrationMethod.NONE:
        return model
    if method == CalibrationMethod.PLATT:
        return _ScalarCalibratorWrapper(
            model, _fit_platt(model.predict_proba(split.X_cal)[:, 1], split.y_cal.values, seed)
        )
    if method == CalibrationMethod.ISOTONIC:
        return _ScalarCalibratorWrapper(
            model,
            _fit_isotonic(model.predict_proba(split.X_cal)[:, 1], split.y_cal.values),
        )
    raise ValueError(f"Unknown calibration method: {method}")


def _fit_platt(scores: np.ndarray, y: np.ndarray, seed: int) -> Any:
    lr = LogisticRegression(max_iter=2000, random_state=seed)
    lr.fit(scores.reshape(-1, 1), y)
    return lambda s: lr.predict_proba(s.reshape(-1, 1))[:, 1]


def _fit_isotonic(scores: np.ndarray, y: np.ndarray) -> Any:
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(scores, y)
    return lambda s: iso.predict(s)


@dataclass
class _ScalarCalibratorWrapper:
    """Apply a scalar calibration mapping to a base model's positive-class proba."""

    base: Any
    map_fn: Any

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw_pos = self.base.predict_proba(X)[:, 1]
        cal_pos = np.clip(self.map_fn(raw_pos), 0.0, 1.0)
        return np.stack([1.0 - cal_pos, cal_pos], axis=1)
