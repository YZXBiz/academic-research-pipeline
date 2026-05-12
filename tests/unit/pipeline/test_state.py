"""Tests for PipelineState.set_stage() merge behavior."""

from __future__ import annotations

from academic_pipeline.core.enums import Stage
from academic_pipeline.pipeline.state import PipelineState


def test_set_stage_preserves_completed_nodes_on_transition():
    """When transitioning from one stage to another, completed_nodes from
    the previous stage must NOT be wiped out."""
    state = PipelineState(topic="test")
    state.set_stage(Stage.RESEARCH)
    # Simulate inner subgraph completions populating completed_nodes
    state.stages["research"]["completed_nodes"] = ["BibliographyNode", "SynthesisNode"]
    state.stages["research"]["current_node"] = "SynthesisNode"

    state.set_stage(Stage.WRITE)

    # Research stage should be marked completed AND retain its completed_nodes
    assert state.stages["research"]["status"] == "completed"
    assert state.stages["research"]["completed_nodes"] == ["BibliographyNode", "SynthesisNode"]
    assert state.stages["research"]["current_node"] == "SynthesisNode"
    # Write stage should be in_progress
    assert state.stages["write"]["status"] == "in_progress"


def test_set_stage_preserves_existing_data_on_new_stage():
    """When entering a stage that already has data (e.g., from prior run),
    the existing data must be preserved, only status changes to in_progress."""
    state = PipelineState(topic="test")
    state.set_stage(Stage.RESEARCH)
    state.stages["write"] = {"status": "completed", "completed_nodes": ["IntakeNode"]}

    state.set_stage(Stage.WRITE)

    assert state.stages["write"]["status"] == "in_progress"
    assert state.stages["write"]["completed_nodes"] == ["IntakeNode"]


def test_set_stage_first_call_initializes_stage_dict():
    """First set_stage call creates the stage dict with status=in_progress."""
    state = PipelineState(topic="test")

    state.set_stage(Stage.RESEARCH)

    assert state.current_stage == Stage.RESEARCH
    assert state.stages["research"]["status"] == "in_progress"


# PRD §6.1.T8 — chain + thesis handoff verification.


def test_pipeline_state_holds_chain_and_thesis_for_writing_handoff():
    """PRD §6.1.T8 — PipelineState carries chain + thesis from research
    to writing phase. Both fields default to None."""
    state = PipelineState(topic="test")
    assert hasattr(state, "chain")
    assert hasattr(state, "thesis")
    assert state.chain is None
    assert state.thesis is None
