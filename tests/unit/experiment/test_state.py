"""Tests for ExperimentState dataclass."""
from __future__ import annotations

from academic_pipeline.experiment.state import ExperimentState


def test_experiment_state_defaults():
    state = ExperimentState(topic="churn prediction", rq_brief="Does XGBoost beat LR?", synthesis="Lit review text")
    assert state.topic == "churn prediction"
    assert state.plan is None
    assert state.results is None
    assert state.analysis is None
    assert state.retry_count == 0
    assert state.error_history == []
    assert state.generated_code is None


def test_pipeline_deps_has_predictor_type():
    from academic_pipeline.core.deps import PipelineDeps
    deps = PipelineDeps.create()
    assert deps.predictor_type == "tabular"
    deps.predictor_type = "timeseries"
    assert deps.predictor_type == "timeseries"


def test_experiment_state_has_predictor_type():
    from academic_pipeline.experiment.state import ExperimentState
    state = ExperimentState(topic="test", predictor_type="multimodal")
    assert state.predictor_type == "multimodal"


def test_experiment_state_predictor_type_defaults_tabular():
    from academic_pipeline.experiment.state import ExperimentState
    state = ExperimentState(topic="test")
    assert state.predictor_type == "tabular"


def test_experiment_state_carries_run_id() -> None:
    """ExperimentState must accept run_id — ConfigWriterNode + DagsterRunNode
    read it to locate output/<run_id>/02-experiment/workspace.
    """
    state = ExperimentState(topic="t", run_id="run-abcd-1234")
    assert state.run_id == "run-abcd-1234"


def test_experiment_state_run_id_defaults_empty() -> None:
    """Default empty string keeps the dataclass safe to construct without args."""
    state = ExperimentState(topic="t")
    assert state.run_id == ""


def test_experiment_subgraph_passes_run_id_into_experiment_state() -> None:
    """The ExperimentState(...) constructor in pipeline/nodes.py must include
    run_id=... so the experiment subgraph can build workspace paths.

    Uses AST to scope the check to the ExperimentState(...) call specifically —
    pipeline/nodes.py also has run_id= in unrelated calls
    (e.g. ``_run_subgraph_with_persistence(..., run_id=...)``).
    """
    import ast
    import inspect

    from academic_pipeline.pipeline import nodes as pipeline_nodes

    tree = ast.parse(inspect.getsource(pipeline_nodes))
    found_call = False
    found_run_id_kwarg = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ExperimentState":
            found_call = True
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "run_id" in kwargs:
                found_run_id_kwarg = True
                break
    assert found_call, "Could not locate ExperimentState(...) constructor call in pipeline/nodes.py"
    assert found_run_id_kwarg, (
        "ExperimentState(...) must include run_id=... so ConfigWriterNode and "
        "DagsterRunNode can build workspace paths from output_dir/<run_id>/02-experiment/."
    )
