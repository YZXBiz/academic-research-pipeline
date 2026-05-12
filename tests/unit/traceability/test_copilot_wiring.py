"""Verify copilot checkpoints are wired into the 3 named pipeline nodes."""

from __future__ import annotations

import inspect

from academic_pipeline.pipeline import nodes


def test_copilot_call_present_in_intake_node() -> None:
    src = inspect.getsource(nodes.IntakeNode)
    assert "copilot_checkpoint" in src, "IntakeNode must call copilot_checkpoint"
    assert "post_intake" in src, "checkpoint name must be 'post_intake'"


def test_copilot_call_present_in_experiment_phase_node() -> None:
    src = inspect.getsource(nodes.ExperimentPhaseNode)
    assert "copilot_checkpoint" in src
    assert "post_experiment_design" in src


def test_copilot_call_present_in_write_phase_node() -> None:
    src = inspect.getsource(nodes.WritePhaseNode)
    assert "copilot_checkpoint" in src
    assert "post_first_draft" in src


def test_pipeline_state_has_copilot_comments_field() -> None:
    """The dict that copilot checkpoints write into."""
    from academic_pipeline.pipeline.state import PipelineState
    state = PipelineState(topic="test")
    assert hasattr(state, "copilot_comments")
    assert state.copilot_comments == {}
