"""AutoGluon code templates — deterministic tools for the code generator agent.

The code generator agent calls these tools to get exact, working AutoGluon
code patterns. This prevents hallucination of AutoGluon APIs.
"""

from __future__ import annotations


async def get_autogluon_tabular_template(
    task_type: str,
    eval_metric: str,
    target_column: str,
    dataset_load_code: str,
) -> str:
    """Get a complete AutoGluon TabularPredictor experiment script template.

    Returns a working Python script that loads data, trains models via
    AutoGluon TabularPredictor, generates figures, runs statistical tests,
    and saves results to results.json.

    Args:
        task_type: "classification" or "regression".
        eval_metric: Primary metric. Classification: "accuracy", "f1", "roc_auc",
            "f1_macro", "precision", "recall". Regression: "rmse", "mae", "r2".
        target_column: Name of the target column in the dataset.
        dataset_load_code: Python code that loads the dataset into a variable
            called `df`. Example: 'from ucimlrepo import fetch_ucirepo; df = fetch_ucirepo(id=109).data.original'
    """
    return f'''"""Auto-generated experiment script using AutoGluon TabularPredictor."""
import json
import os
import random
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

random.seed(42)
np.random.seed(42)
warnings.filterwarnings("ignore")

os.makedirs("figures", exist_ok=True)

# ── 1. Load data ──────────────────────────────────────────────
{dataset_load_code}

print(f"Dataset shape: {{df.shape}}")
print(f"Target: {target_column}")
print(f"Missing values: {{df.isnull().sum().sum()}}")
data_summary = f"{{df.shape[0]}} rows x {{df.shape[1]}} cols, {{df.isnull().sum().sum()}} missing"

# ── 2. Train/test split ──────────────────────────────────────
from sklearn.model_selection import train_test_split
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
print(f"Train: {{train_df.shape}}, Test: {{test_df.shape}}")

# ── 3. AutoGluon training ────────────────────────────────────
from autogluon.tabular import TabularPredictor

predictor = TabularPredictor(
    label="{target_column}",
    eval_metric="{eval_metric}",
    path="ag_models",
    verbosity=1,
).fit(
    train_data=train_df,
    presets="medium_quality",
    time_limit=300,
)

# ── 4. Results ───────────────────────────────────────────────
leaderboard = predictor.leaderboard(test_df, silent=True)
print("\\n=== Leaderboard ===")
print(leaderboard.to_string())

eval_results = predictor.evaluate(test_df, silent=True)
print(f"\\nEval results: {{eval_results}}")

# Extract per-model metrics
metrics = {{}}
for _, row in leaderboard.iterrows():
    model_name = row["model"]
    metrics[model_name] = {{"{eval_metric}": float(row["score_test"])}}

# ── 5. Feature importance ────────────────────────────────────
try:
    importance = predictor.feature_importance(test_df, silent=True)
    print("\\n=== Feature Importance (top 10) ===")
    print(importance.head(10).to_string())
except Exception as e:
    print(f"Feature importance failed: {{e}}")
    importance = pd.DataFrame()

# ── 6. Statistical tests ─────────────────────────────────────
statistical_tests = {{}}
model_names = list(leaderboard["model"].head(5))
if len(model_names) >= 2:
    best_model = model_names[0]
    for other_model in model_names[1:]:
        try:
            preds_best = predictor.predict(test_df, model=best_model)
            preds_other = predictor.predict(test_df, model=other_model)
            if "{task_type}" == "classification":
                correct_best = (preds_best == test_df["{target_column}"]).astype(int)
                correct_other = (preds_other == test_df["{target_column}"]).astype(int)
                diff = correct_best - correct_other
            else:
                errors_best = abs(preds_best - test_df["{target_column}"])
                errors_other = abs(preds_other - test_df["{target_column}"])
                diff = errors_other - errors_best
            if diff.std() > 0:
                stat_val, p_value = stats.wilcoxon(diff[diff != 0])
                statistical_tests[f"{{best_model}}_vs_{{other_model}}"] = {{
                    "test_name": "wilcoxon",
                    "p_value": round(float(p_value), 6),
                    "significant": bool(p_value < 0.05),
                }}
        except Exception as e:
            print(f"Statistical test {{best_model}} vs {{other_model}} failed: {{e}}")

# ── 7. Figures ───────────────────────────────────────────────
# Performance comparison bar chart
fig, ax = plt.subplots(figsize=(10, 6))
top_models = leaderboard.head(10).sort_values("score_test")
ax.barh(top_models["model"], top_models["score_test"])
ax.set_xlabel("{eval_metric}")
ax.set_title("Model Performance Comparison (AutoGluon)")
fig.tight_layout()
fig.savefig("figures/fig_performance_comparison.png", dpi=150)
plt.close()

# Feature importance chart
if not importance.empty:
    fig, ax = plt.subplots(figsize=(10, 6))
    top_features = importance.head(15)
    ax.barh(range(len(top_features)), top_features["importance"])
    ax.set_yticks(range(len(top_features)))
    ax.set_yticklabels(top_features.index)
    ax.set_xlabel("Importance")
    ax.set_title("Top 15 Feature Importances")
    fig.tight_layout()
    fig.savefig("figures/fig_feature_importance.png", dpi=150)
    plt.close()

# ── 8. Save results ──────────────────────────────────────────
figures_list = [f for f in os.listdir("figures") if f.endswith(".png")]

results = {{
    "metrics": metrics,
    "cv_scores": {{}},
    "statistical_tests": statistical_tests,
    "data_summary": data_summary,
    "figures": figures_list,
    "leaderboard": leaderboard.head(10).to_dict(orient="records"),
}}

with open("results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\\n=== Results saved to results.json ===")
print(f"Models compared: {{len(metrics)}}")
print(f"Statistical tests: {{len(statistical_tests)}}")
print(f"Figures: {{len(figures_list)}}")
'''


async def get_autogluon_timeseries_template(
    eval_metric: str,
    target_column: str,
    prediction_length: int,
    dataset_load_code: str,
) -> str:
    """Get a complete AutoGluon TimeSeriesPredictor experiment script template.

    Returns a working Python script that loads time series data, trains models
    via AutoGluon TimeSeriesPredictor, generates figures, and saves results
    to results.json.

    Args:
        eval_metric: Primary metric. Common: "WQL", "MASE", "MAPE", "RMSE",
            "WAPE", "SQL", "MSE", "MAE", "mean_wQuantileLoss".
        target_column: Name of the target column in the dataset.
        prediction_length: Number of time steps to forecast.
        dataset_load_code: Python code that loads the dataset into a variable
            called `df` (must be a TimeSeriesDataFrame or convertible to one).
    """
    return f'''"""Auto-generated experiment script using AutoGluon TimeSeriesPredictor."""
import json
import os
import random
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)
warnings.filterwarnings("ignore")

os.makedirs("figures", exist_ok=True)

# ── 1. Load data ──────────────────────────────────────────────
from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor

{dataset_load_code}

print(f"Dataset shape: {{df.shape}}")
print(f"Target: {target_column}")
print(f"Prediction length: {prediction_length}")
data_summary = f"{{df.shape[0]}} rows x {{df.shape[1]}} cols, prediction_length={prediction_length}"

# ── 2. Train/test split ──────────────────────────────────────
test_df = df.slice_by_timestep(-{prediction_length}, None)
train_df = df.slice_by_timestep(None, -{prediction_length})
print(f"Train: {{train_df.shape}}, Test: {{test_df.shape}}")

# ── 3. AutoGluon training ────────────────────────────────────
predictor = TimeSeriesPredictor(
    target="{target_column}",
    prediction_length={prediction_length},
    eval_metric="{eval_metric}",
    path="ag_models",
    verbosity=1,
).fit(
    train_data=train_df,
    presets="medium_quality",
    time_limit=300,
)

# ── 4. Results ───────────────────────────────────────────────
leaderboard = predictor.leaderboard(test_df, silent=True)
print("\\n=== Leaderboard ===")
print(leaderboard.to_string())

eval_results = predictor.evaluate(test_df, silent=True)
print(f"\\nEval results: {{eval_results}}")

# Extract per-model metrics
metrics = {{}}
for _, row in leaderboard.iterrows():
    model_name = row["model"]
    metrics[model_name] = {{"{eval_metric}": float(row["score_test"])}}

# ── 5. Statistical tests ─────────────────────────────────────
statistical_tests = {{}}

# ── 6. Figures ───────────────────────────────────────────────
# Forecast plot
try:
    predictions = predictor.predict(train_df)
    fig, ax = plt.subplots(figsize=(12, 6))
    item_ids = list(test_df.item_ids[:3])  # Plot up to 3 series
    for item_id in item_ids:
        test_slice = test_df.loc[item_id]
        pred_slice = predictions.loc[item_id]
        ax.plot(test_slice.index, test_slice["{target_column}"], label=f"{{item_id}} actual", linestyle="--")
        ax.plot(pred_slice.index, pred_slice["mean"], label=f"{{item_id}} forecast")
    ax.set_xlabel("Time")
    ax.set_ylabel("{target_column}")
    ax.set_title("Time Series Forecast vs Actual")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig("figures/fig_forecast.png", dpi=150)
    plt.close()
except Exception as e:
    print(f"Forecast plot failed: {{e}}")

# Performance comparison bar chart
fig, ax = plt.subplots(figsize=(10, 6))
top_models = leaderboard.head(10).sort_values("score_test")
ax.barh(top_models["model"], top_models["score_test"])
ax.set_xlabel("{eval_metric}")
ax.set_title("Model Performance Comparison (AutoGluon TimeSeriesPredictor)")
fig.tight_layout()
fig.savefig("figures/fig_performance_comparison.png", dpi=150)
plt.close()

# ── 7. Save results ──────────────────────────────────────────
figures_list = [f for f in os.listdir("figures") if f.endswith(".png")]

results = {{
    "metrics": metrics,
    "cv_scores": {{}},
    "statistical_tests": statistical_tests,
    "data_summary": data_summary,
    "figures": figures_list,
    "leaderboard": leaderboard.head(10).to_dict(orient="records"),
}}

with open("results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\\n=== Results saved to results.json ===")
print(f"Models compared: {{len(metrics)}}")
print(f"Figures: {{len(figures_list)}}")
'''


async def get_autogluon_multimodal_template(
    problem_type: str,
    eval_metric: str,
    target_column: str,
    dataset_load_code: str,
) -> str:
    """Get a complete AutoGluon MultiModalPredictor experiment script template.

    Returns a working Python script that loads data, trains models via
    AutoGluon MultiModalPredictor, generates figures, and saves results
    to results.json.

    Args:
        problem_type: "classification", "regression", "object_detection",
            "named_entity_recognition", etc.
        eval_metric: Primary metric. Classification: "accuracy", "f1", "roc_auc".
            Regression: "rmse", "mae", "r2".
        target_column: Name of the target column in the dataset.
        dataset_load_code: Python code that loads the dataset into a variable
            called `df`. Example: 'import pandas as pd; df = pd.read_csv("data.csv")'
    """
    return f'''"""Auto-generated experiment script using AutoGluon MultiModalPredictor."""
import json
import os
import random
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)
warnings.filterwarnings("ignore")

os.makedirs("figures", exist_ok=True)

# ── 1. Load data ──────────────────────────────────────────────
{dataset_load_code}

print(f"Dataset shape: {{df.shape}}")
print(f"Target: {target_column}")
print(f"Problem type: {problem_type}")
print(f"Missing values: {{df.isnull().sum().sum()}}")
data_summary = f"{{df.shape[0]}} rows x {{df.shape[1]}} cols, {{df.isnull().sum().sum()}} missing"

# ── 2. Train/test split ──────────────────────────────────────
from sklearn.model_selection import train_test_split
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
print(f"Train: {{train_df.shape}}, Test: {{test_df.shape}}")

# ── 3. AutoGluon training ────────────────────────────────────
from autogluon.multimodal import MultiModalPredictor

predictor = MultiModalPredictor(
    label="{target_column}",
    problem_type="{problem_type}",
    eval_metric="{eval_metric}",
    path="ag_models",
    verbosity=1,
).fit(
    train_data=train_df,
    presets="medium_quality",
    time_limit=300,
)

# ── 4. Results ───────────────────────────────────────────────
eval_results = predictor.evaluate(test_df)
print(f"\\nEval results: {{eval_results}}")

predictions = predictor.predict(test_df)

if isinstance(eval_results, dict):
    _score = eval_results.get("{eval_metric}", list(eval_results.values())[0])
else:
    _score = eval_results
metrics = {{"MultiModalPredictor": {{"{eval_metric}": float(_score)}}}}

# ── 5. Statistical tests ─────────────────────────────────────
statistical_tests = {{}}

# ── 6. Figures ───────────────────────────────────────────────
# Performance bar chart
fig, ax = plt.subplots(figsize=(8, 5))
metric_names = list(metrics["MultiModalPredictor"].keys())
metric_values = list(metrics["MultiModalPredictor"].values())
ax.bar(metric_names, metric_values)
ax.set_ylabel("Score")
ax.set_title("MultiModalPredictor Performance")
fig.tight_layout()
fig.savefig("figures/fig_performance_comparison.png", dpi=150)
plt.close()

# Confusion matrix for classification
if "{problem_type}" == "classification":
    try:
        from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
        y_true = test_df["{target_column}"]
        cm = confusion_matrix(y_true, predictions)
        fig, ax = plt.subplots(figsize=(8, 6))
        ConfusionMatrixDisplay(cm).plot(ax=ax)
        ax.set_title("Confusion Matrix")
        fig.tight_layout()
        fig.savefig("figures/fig_confusion_matrix.png", dpi=150)
        plt.close()
    except Exception as e:
        print(f"Confusion matrix failed: {{e}}")

# ── 7. Save results ──────────────────────────────────────────
figures_list = [f for f in os.listdir("figures") if f.endswith(".png")]

results = {{
    "metrics": metrics,
    "cv_scores": {{}},
    "statistical_tests": statistical_tests,
    "data_summary": data_summary,
    "figures": figures_list,
    "leaderboard": [{{"model": "MultiModalPredictor", **metrics["MultiModalPredictor"]}}],
}}

with open("results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)

print("\\n=== Results saved to results.json ===")
print(f"Figures: {{len(figures_list)}}")
'''


async def get_autogluon_presets_info() -> str:
    """Get information about AutoGluon presets and configuration options.

    Returns a reference table of presets, eval metrics, and time limits
    for all three predictor types (Tabular, TimeSeries, MultiModal).
    """
    return """AutoGluon Presets Reference:

=== TabularPredictor ===

PRESETS (use in .fit(presets=...)):
  "medium_quality" — DEFAULT. ~5 min. Trains LightGBM, XGBoost, CatBoost, NN, RF, KNN.
  "good_quality"   — ~10 min. Adds hyperparameter tuning.
  "high_quality"   — ~30 min. AVOID (may exceed timeout).
  "best_quality"   — Hours. NEVER USE (exceeds timeout).

EVAL METRICS:
  Classification: "accuracy", "f1", "roc_auc", "f1_macro", "f1_weighted", "precision", "recall", "log_loss"
  Regression: "rmse", "mae", "r2", "mape", "median_absolute_error"

KEY RULES:
  - ALWAYS do train_test_split BEFORE .fit() — AutoGluon does internal CV but you need a holdout
  - NEVER call .fit() on test data
  - The path="ag_models" directory is ephemeral — don't include it in results

=== TimeSeriesPredictor ===

PRESETS:
  "medium_quality" — DEFAULT. ~5 min. Trains ETS, Theta, DeepAR, PatchTST, TemporalFusionTransformer.
  "good_quality"   — ~10 min. More models + hyperparameter tuning.
  "high_quality"   — ~30 min. AVOID (may exceed timeout).
  "best_quality"   — Hours. NEVER USE (exceeds timeout).

EVAL METRICS:
  "WQL" (weighted quantile loss) — DEFAULT, lower is better
  "MASE", "MAPE", "RMSE", "WAPE", "SQL", "MSE", "MAE", "mean_wQuantileLoss"

KEY RULES:
  - Data must be a TimeSeriesDataFrame with item_id, timestamp, and target columns
  - Split with .slice_by_timestep(), NOT train_test_split
  - prediction_length must match the forecast horizon
  - target= (not label=) is used for TimeSeriesPredictor

=== MultiModalPredictor ===

PRESETS:
  "medium_quality" — DEFAULT. ~5 min. Balanced speed/quality.
  "high_quality"   — ~15 min. Better accuracy, more compute.
  "best_quality"   — Hours. NEVER USE (exceeds timeout).

EVAL METRICS:
  Classification: "accuracy", "f1", "roc_auc", "log_loss"
  Regression: "rmse", "mae", "r2"
  Other: depends on problem_type

PROBLEM TYPES:
  "classification", "regression", "object_detection", "named_entity_recognition",
  "feature_extraction", "text_similarity"

KEY RULES:
  - problem_type must be set explicitly
  - Supports tabular, text, image, and multimodal data
  - Use train_test_split for holdout evaluation
  - label= (not target=) is used for MultiModalPredictor

=== GLOBAL RULES (all predictors) ===

TIME LIMIT:
  Always set time_limit=300 (5 minutes) to stay within the 10-min execution timeout.
  AutoGluon will train as many models as possible within the limit.

  - NEVER use presets="best_quality"
  - NEVER omit time_limit
  - The path="ag_models" directory is ephemeral — don't include it in results
"""
