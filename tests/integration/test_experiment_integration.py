"""Integration test for experiment subgraph with mocked agents."""
from __future__ import annotations

from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.models.experiment import (
    DatasetSpec,
    ExperimentAnalysis,
    ExperimentPlan,
    MethodSpec,
)


def _make_plan_json() -> str:
    plan = ExperimentPlan(
        research_question="Does AutoGluon beat LogisticRegression on tabular data?",
        hypothesis="AutoGluon achieves >2% accuracy improvement via ensemble stacking",
        experiment_type="classification",
        dataset_sources=[
            DatasetSpec(
                name="iris", source="huggingface",
                download_instruction="from datasets import load_dataset; ds = load_dataset('scikit-learn/iris')",
                expected_shape="(150, 5)", target_column="target",
            ),
        ],
        baseline_methods=[MethodSpec(name="LogisticRegression", implementation="sklearn.linear_model.LogisticRegression", is_baseline=True)],
        proposed_methods=[MethodSpec(name="AutoGluon", implementation="autogluon.tabular.TabularPredictor", is_baseline=False)],
        evaluation_metrics=["accuracy"],
        success_criteria=">2% improvement",
        required_figures=["performance_bar_chart"],
        estimated_runtime_minutes=1,
        python_packages=["autogluon.tabular"],
    )
    return plan.model_dump_json()


def _make_analysis_json() -> str:
    analysis = ExperimentAnalysis(
        results_interpretation="XGBoost outperforms LR",
        baseline_comparisons=[],
        domain_implications="Tree models capture nonlinear feature interactions",
        domain_theory_connection="Aligns with ensemble learning theory",
        limitations=["Single dataset"],
        threats_to_validity=["Small sample size"],
        key_findings=["XGB achieves 0.95 accuracy"],
        figure_references=["Figure 1"],
        suggested_paper_structure="imrad",
    )
    return analysis.model_dump_json()


def test_experiment_state_flow():
    """Verify ExperimentState can hold all artifacts from a complete run."""
    state = ExperimentState(
        topic="Churn prediction comparison",
        rq_brief="Does XGBoost beat LR?",
        synthesis="Literature shows mixed results...",
    )

    plan = ExperimentPlan.model_validate_json(_make_plan_json())
    state.plan = plan
    assert state.plan.experiment_type == "classification"

    analysis = ExperimentAnalysis.model_validate_json(_make_analysis_json())
    state.analysis = analysis
    assert state.analysis.suggested_paper_structure == "imrad"
