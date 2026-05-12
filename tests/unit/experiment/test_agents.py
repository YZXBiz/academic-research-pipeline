"""Tests for experiment agent registry."""
from __future__ import annotations


def test_agent_registry_loads():
    from academic_pipeline.experiment.agents import agents

    assert "experiment_classifier" in agents
    assert "experiment_designer" in agents
    assert "result_analyzer" in agents
    assert "experiment_improver" in agents
    assert "figure_reviewer" in agents
    assert "ml_engineer" in agents
    assert "experiment_judge" in agents
    # code_generator and code_fixer removed — replaced by ml_engineer
    assert "code_generator" not in agents
    assert "code_fixer" not in agents
    # Spec 7 — exploration breadth bundle agents (used when flag on)
    assert "experiment_designer_bundle" in agents
    assert "design_scorer" in agents
    assert "design_comparator" in agents
    # v2 Dagster cutover — config_writer replaces ml_engineer + code generation
    assert "config_writer" in agents
    assert len(agents) == 11
