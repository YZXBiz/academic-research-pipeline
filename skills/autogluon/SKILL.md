---
name: autogluon
description: AutoGluon full API reference — TabularPredictor, TimeSeriesPredictor, MultiModalPredictor patterns, presets, eval metrics, and figure generation for experiment code generation.
---

# AutoGluon Reference — All Predictor Types

AutoGluon has 3 predictors. Use the one matching the classified `predictor_type`.

---

## 1. TabularPredictor (predictor_type = tabular)

### Core Pattern

```python
from autogluon.tabular import TabularPredictor

predictor = TabularPredictor(label="target_column", eval_metric="accuracy", path="ag_models").fit(
    train_data=train_df, time_limit=300, presets="medium_quality"
)
leaderboard = predictor.leaderboard(test_df, silent=True)
```

### Eval Metrics

| Task | eval_metric | Alternatives |
|------|------------|-------------|
| Binary classification | `"accuracy"` | `"f1"`, `"roc_auc"`, `"balanced_accuracy"` |
| Multiclass | `"accuracy"` | `"f1_weighted"`, `"balanced_accuracy"` |
| Regression | `"rmse"` | `"mae"`, `"r2"`, `"mse"` |

AutoGluon auto-detects problem type from the label column. Override with `problem_type="binary"`.

### Train/Test Split

```python
from sklearn.model_selection import train_test_split
train_df, test_df = train_test_split(df, test_size=0.2, random_state=SEED, stratify=df["target"])
```

### Leaderboard

```python
leaderboard = predictor.leaderboard(test_df, silent=True)
```

Returns DataFrame with: `model`, `score_test`, `score_val`, `pred_time_test`, `fit_time`, `stack_level`.
`score_test` is always higher-is-better (AutoGluon negates metrics like RMSE).

### Feature Importance

```python
importance = predictor.feature_importance(test_df, silent=True)
```

Returns DataFrame with: `importance`, `stddev`, `p_value`. Uses permutation importance.

### Predictions

```python
y_pred = predictor.predict(test_df)
y_proba = predictor.predict_proba(test_df)  # classification only
```

---

## 2. TimeSeriesPredictor (predictor_type = timeseries)

### Core Pattern

```python
from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor

data = TimeSeriesDataFrame(df)  # must have item_id, timestamp, target columns

predictor = TimeSeriesPredictor(
    target="target", prediction_length=48, eval_metric="WQL", path="ag_models"
)
predictor.fit(train_data=train_df, presets="medium_quality", time_limit=300)
leaderboard = predictor.leaderboard(test_df, silent=True)
predictions = predictor.predict(train_df)
```

### Data Format

TimeSeriesDataFrame requires 3 columns:
- `item_id` — identifier for each time series
- `timestamp` — datetime index
- `target` — the value to forecast

### Train/Test Split (TEMPORAL — never random)

```python
test_df = data.slice_by_timestep(-prediction_length, None)
train_df = data.slice_by_timestep(None, -prediction_length)
```

### Eval Metrics

| Metric | Type | Notes |
|--------|------|-------|
| `"WQL"` | Probabilistic (default) | Weighted quantile loss |
| `"SQL"` | Probabilistic | Scaled quantile loss |
| `"MAE"` | Point | Mean absolute error |
| `"MASE"` | Point | < 1 means better than naive |
| `"RMSE"` | Point | Root mean squared error |
| `"SMAPE"` | Point | Symmetric MAPE |
| `"MAPE"` | Point | Mean absolute percentage error |

### Models Included

ETS, ARIMA (StatsForecast), DeepAR, TFT, PatchTST (GluonTS), Chronos-2, LightGBM-based.

### Known Covariates (optional)

```python
predictor = TimeSeriesPredictor(
    target="target", prediction_length=48,
    known_covariates_names=["holiday", "day_of_week"],
)
```

### Forecast Plot

```python
item_ids = list(train_df.item_ids[:3])
for item_id in item_ids:
    ts = train_df.loc[item_id]["target"].tail(100)
    pred = predictions.loc[item_id]
    plt.plot(ts.index, ts.values, label="History")
    plt.plot(pred.index, pred["mean"], label="Forecast")
    if "0.1" in pred.columns and "0.9" in pred.columns:
        plt.fill_between(pred.index, pred["0.1"], pred["0.9"], alpha=0.2)
```

---

## 3. MultiModalPredictor (predictor_type = multimodal)

### Core Pattern

```python
from autogluon.multimodal import MultiModalPredictor

predictor = MultiModalPredictor(
    label="label_column", problem_type="classification",
    eval_metric="accuracy", path="ag_models"
)
predictor.fit(train_data=train_df, presets="medium_quality", time_limit=300)
eval_results = predictor.evaluate(test_df)
predictions = predictor.predict(test_df)
```

### Problem Types

| problem_type | Use Case |
|-------------|----------|
| `"classification"` | Text/image/tabular classification |
| `"binary"` | Binary classification |
| `"multiclass"` | Multiclass classification |
| `"regression"` | Text/image/tabular regression |
| `"ner"` | Named entity recognition |
| `"object_detection"` | Object detection |
| `"text_similarity"` | Text-text semantic matching |
| `"image_similarity"` | Image-image semantic matching |
| `"image_text_similarity"` | Text-image semantic matching |
| `"feature_extraction"` | Embedding extraction (inference only) |
| `"few_shot_classification"` | Few-shot classification |
| `"semantic_segmentation"` | Segment Anything |

### Eval Metrics

| Task | Metrics |
|------|---------|
| Classification | `"accuracy"`, `"f1"`, `"roc_auc"` |
| Regression | `"rmse"`, `"mae"`, `"r2"` |
| NER | `"overall_recall"`, `"overall_precision"`, `"overall_f1"` |
| Object Detection | `"map"` |

### Data Format

- Text: DataFrame with string columns
- Image: DataFrame with columns containing file paths to images
- Tabular: DataFrame with numeric/categorical columns
- Mixed: Any combination of the above

### Train/Test Split

```python
from sklearn.model_selection import train_test_split
train_df, test_df = train_test_split(df, test_size=0.2, random_state=SEED)
```

### Backbones

AutoMM wraps HuggingFace Transformers (text), TIMM (image), MMDetection (object detection). Do NOT import these directly.

---

## Common Rules (ALL Predictor Types)

### Presets

| Preset | Use | Time |
|--------|-----|------|
| `"medium_quality"` | **DEFAULT. Always start here.** | ~5 min |
| `"good_quality"` | Slightly better results | ~10 min |
| `"high_quality"` | Avoid — may exceed timeout | ~20 min |
| `"best_quality"` | **NEVER USE** | hours |

### time_limit

**MANDATORY**: Always pass `time_limit=300`. No exceptions.

### Figures

Always call `plt.close(fig)` after saving. Never call `plt.show()`.

### results.json

Every experiment must write `results.json` with keys: `metrics`, `cv_scores`, `statistical_tests`, `data_summary`, `figures`.

### Statistical Tests

AutoGluon does NOT provide significance tests. Add them manually:

```python
from scipy import stats
stat_val, p_value = stats.wilcoxon(scores_a, scores_b)
```

### Common Pitfalls

1. **NEVER use `best_quality` preset.** Exceeds timeout, may OOM.
2. **NEVER call fit on test data.** Split first, fit on train only.
3. **NEVER forget `time_limit=300`.** Without it, AutoGluon runs indefinitely.
4. **NEVER call `plt.show()`.** No display in Docker. Use `savefig` + `close`.
5. **NEVER import AutoGluon internals directly** (`statsforecast`, `gluonts`, `transformers`, `timm`). Use the Predictor API.
6. **For timeseries: NEVER random split.** Use temporal `.slice_by_timestep()`.
7. **Do NOT set `num_gpus` in the sandbox.** Docker container may not have GPU.
8. **Clean up model artifacts:**
   ```python
   import shutil
   shutil.rmtree("ag_models", ignore_errors=True)
   ```
