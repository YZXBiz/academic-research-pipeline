# tests/test_experiment_models.py
"""Tests for experiment domain models."""
from __future__ import annotations

from academic_pipeline.models.experiment import (
    BaselineComparison,
    DatasetSpec,
    ExperimentAnalysis,
    ExperimentClassification,
    ExperimentPlan,
    ExperimentResults,
    FigureArtifact,
    MethodSpec,
    StatisticalTest,
)


def test_experiment_classification_frozen():
    ec = ExperimentClassification(
        needs_experiments=True, reasoning="Topic involves model comparison on public data",
        suggested_experiment_type="benchmark_comparison", suggested_datasets=["Telco Churn"],
    )
    assert ec.needs_experiments is True
    assert ec.suggested_experiment_type == "benchmark_comparison"

def test_dataset_spec():
    ds = DatasetSpec(name="Telco Churn", source="sklearn",
        download_instruction="from sklearn.datasets import fetch_openml; data = fetch_openml('telco-customer-churn')",
        expected_shape="~7k rows, 20 features, 1 target", target_column="Churn")
    assert ds.source == "sklearn"

def test_method_spec():
    ms = MethodSpec(name="XGBoost", implementation="xgboost.XGBClassifier(n_estimators=100)", is_baseline=False)
    assert ms.is_baseline is False

def test_experiment_plan():
    plan = ExperimentPlan(
        research_question="Does feature engineering improve churn prediction?",
        hypothesis="Temporal features improve AUC by >2%", experiment_type="ablation_study",
        dataset_sources=[
            DatasetSpec(
                name="Telco", source="huggingface",
                download_instruction="from datasets import load_dataset; ds = load_dataset('scikit-learn/churn-prediction')",
                expected_shape="7k x 20", target_column="Churn",
            ),
        ],
        baseline_methods=[MethodSpec(name="LR", implementation="LogisticRegression()", is_baseline=True)],
        proposed_methods=[MethodSpec(name="AutoGluon", implementation="TabularPredictor(label='Churn')", is_baseline=False)],
        evaluation_metrics=["accuracy", "f1_macro", "roc_auc"],
        success_criteria="Proposed achieves >2% AUC improvement",
        required_figures=["performance_bar_chart", "shap_summary"],
        estimated_runtime_minutes=5, python_packages=["pandas", "sklearn", "xgboost", "shap"],
    )
    assert plan.experiment_type == "ablation_study"
    assert len(plan.required_figures) == 2

def test_statistical_test():
    st = StatisticalTest(test_name="wilcoxon", p_value=0.03, significant=True, effect_size=0.45)
    assert st.significant is True

def test_figure_artifact():
    fa = FigureArtifact(figure_type="performance_bar_chart", filename="fig_performance.png",
        caption="Figure 1: Performance comparison.", data_base64="iVBORw0KGgo=")
    assert fa.width_inches == 8.0

def test_experiment_results():
    er = ExperimentResults(
        success=True, metrics={"XGB": {"accuracy": 0.87, "f1": 0.83}},
        cv_scores={"XGB": [0.85, 0.87, 0.86, 0.88, 0.87]},
        statistical_tests={
            "xgb_vs_lr": StatisticalTest(
                test_name="wilcoxon", p_value=0.02, significant=True, effect_size=0.5,
            ),
        },
        execution_time_seconds=120.5, stdout="Training complete.", stderr="",
        code="import sklearn...", figures=[], data_summary="7043 rows x 20 cols, 0 missing", retries_used=0,
    )
    assert er.success is True

def test_baseline_comparison():
    bc = BaselineComparison(
        baseline_name="Random Forest (default)", source="our_experiment",
        metric_comparison={"accuracy": (0.85, 0.87)},
        where_we_agree="Both rank tenure as top feature",
        where_we_differ="XGB captures interaction effects RF misses",
        why_we_differ="Gradient boosting explicitly models feature interactions",
        statistical_significance="p=0.03, Wilcoxon, significant at alpha=0.05",
    )
    assert bc.source == "our_experiment"

def test_experiment_classification_has_predictor_type():
    ec = ExperimentClassification(
        needs_experiments=True,
        reasoning="Time series forecasting task",
        predictor_type="timeseries",
        suggested_experiment_type="forecasting_benchmark",
        suggested_datasets=["ETTh1"],
    )
    assert ec.predictor_type == "timeseries"


def test_experiment_classification_predictor_type_defaults_none():
    """When predictor_type is omitted it defaults to None.

    The classifier agent must explicitly set predictor_type when
    needs_experiments=True. Defaulting to None prevents misleading
    'tabular' values appearing in traces when no experiments are needed.
    """
    ec = ExperimentClassification(
        needs_experiments=True,
        reasoning="Standard ML",
    )
    assert ec.predictor_type is None


def test_experiment_plan_no_autogluon_validator():
    """ExperimentPlan should accept plans without AutoGluon — validation moved to output_validator."""
    plan = ExperimentPlan(
        research_question="Does ARIMA beat Theta on M4?",
        hypothesis="ARIMA wins on hourly data",
        experiment_type="forecasting_benchmark",
        dataset_sources=[
            DatasetSpec(
                name="M4 Hourly", source="autogluon_s3",
                download_instruction="from autogluon.timeseries import TimeSeriesDataFrame; data = TimeSeriesDataFrame('https://autogluon.s3.amazonaws.com/datasets/timeseries/m4_hourly/train.csv')",
                expected_shape="400+ time series", target_column="target",
            ),
        ],
        baseline_methods=[MethodSpec(name="Naive", implementation="NaiveModel()", is_baseline=True)],
        proposed_methods=[MethodSpec(name="TimeSeriesPredictor", implementation="TimeSeriesPredictor(target='target', prediction_length=48)", is_baseline=False)],
        evaluation_metrics=["WQL", "MASE"],
        success_criteria="Proposed achieves lower WQL",
    )
    assert plan.experiment_type == "forecasting_benchmark"


def test_experiment_plan_non_huggingface_dataset_allowed():
    """ExperimentPlan should accept non-HuggingFace datasets — validation moved to output_validator."""
    plan = ExperimentPlan(
        research_question="Test question",
        hypothesis="Test hypothesis",
        experiment_type="benchmark_comparison",
        dataset_sources=[
            DatasetSpec(
                name="M4", source="autogluon_s3",
                download_instruction="from autogluon.timeseries import TimeSeriesDataFrame; data = TimeSeriesDataFrame('https://autogluon.s3.amazonaws.com/datasets/timeseries/m4_hourly/train.csv')",
                expected_shape="400+ series", target_column="target",
            ),
        ],
        baseline_methods=[MethodSpec(name="Baseline", implementation="DummyRegressor()", is_baseline=True)],
        proposed_methods=[MethodSpec(name="AG", implementation="TabularPredictor(label='target')", is_baseline=False)],
        evaluation_metrics=["rmse"],
        success_criteria="Lower RMSE",
    )
    assert plan.dataset_sources[0].source == "autogluon_s3"


def test_experiment_analysis():
    ea = ExperimentAnalysis(
        results_interpretation="XGBoost outperforms baselines on all metrics",
        baseline_comparisons=[], domain_implications="Feature importance aligns with economic theory of churn",
        domain_theory_connection="Top features (tenure, charges) match CLV theory",
        alternative_explanations=["Performance gap may be due to hyperparameter advantage"],
        shap_interpretation="Tenure has negative SHAP values for churn=1",
        limitations=["Single dataset", "No temporal validation"],
        threats_to_validity=["Possible data leakage in monthly charges"],
        key_findings=["XGBoost achieves 0.87 AUC", "Temporal features add 2.1% AUC"],
        figure_references=["Figure 1 shows performance comparison"],
        suggested_paper_structure="imrad",
    )
    assert ea.suggested_paper_structure == "imrad"
