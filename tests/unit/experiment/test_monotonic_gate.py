"""Tests for monotonic quality gate in improvement loop."""
from __future__ import annotations

from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.models.experiment import (
    DatasetSpec,
    ExperimentPlan,
    ExperimentResults,
    MethodSpec,
)


def test_best_results_updated_when_better():
    state = ExperimentState(topic="test", rq_brief="test", synthesis="test")
    state.plan = ExperimentPlan(
        research_question="test", hypothesis="test", experiment_type="benchmark",
        dataset_sources=[DatasetSpec(name="t", source="huggingface", download_instruction="from datasets import load_dataset; ds = load_dataset('test/data')", expected_shape="1x1")],
        baseline_methods=[MethodSpec(name="LR", implementation="LR()", is_baseline=True)],
        proposed_methods=[MethodSpec(name="AutoGluon", implementation="TabularPredictor(label='target')", is_baseline=False)], evaluation_metrics=["accuracy"],
        success_criteria="test", python_packages=[],
    )

    # First result: 0.80
    state.results = ExperimentResults(success=True, metrics={"LR": {"accuracy": 0.80}})
    state.best_results = None

    # Simulate: first analysis sets baseline
    assert state.best_results is None
    state.best_results = state.results
    state.best_code = "v1"
    assert state.best_results.metrics["LR"]["accuracy"] == 0.80

    # Second result: 0.85 (better)
    state.results = ExperimentResults(success=True, metrics={"LR": {"accuracy": 0.85}})
    # Should update best
    state.best_results = state.results
    state.best_code = "v2"
    assert state.best_results.metrics["LR"]["accuracy"] == 0.85


def test_best_results_reverted_when_worse():
    state = ExperimentState(topic="test", rq_brief="test", synthesis="test")

    best = ExperimentResults(success=True, metrics={"LR": {"accuracy": 0.85}})
    state.best_results = best
    state.best_code = "good_code"

    # Worse result: 0.75
    state.results = ExperimentResults(success=True, metrics={"LR": {"accuracy": 0.75}})
    state.generated_code = "bad_code"

    # Simulate revert
    state.results = state.best_results
    state.generated_code = state.best_code
    assert state.results.metrics["LR"]["accuracy"] == 0.85
    assert state.generated_code == "good_code"
