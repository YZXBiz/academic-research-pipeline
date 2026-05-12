"""Tests for experiment orchestrator nodes and state fields."""
from __future__ import annotations

from academic_pipeline.pipeline.state import PipelineState


def test_pipeline_state_has_experiment_fields():
    state = PipelineState()
    assert state.experiment_classification is None
    assert state.experiment_plan is None
    assert state.experiment_code is None
    assert state.experiment_results is None
    assert state.experiment_analysis is None
    assert state.experiment_figures == []
    assert state.experiment_fix_count == 0
