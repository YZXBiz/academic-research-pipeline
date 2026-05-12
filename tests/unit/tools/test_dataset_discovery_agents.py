"""Tests for dataset discovery agent changes."""
from __future__ import annotations


def test_designer_has_exa_tools():
    from academic_pipeline.experiment.agents import agents
    designer = agents["experiment_designer"]
    assert designer is not None
    # 7 baseline + 3 from Spec 7 (experiment_designer_bundle, design_scorer,
    # design_comparator) + 1 from v2 cutover (config_writer)
    assert len(agents) == 11
