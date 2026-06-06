# tests/test_experiment_graph.py
"""Tests for experiment subgraph graph and nodes."""
from __future__ import annotations

from academic_pipeline.experiment.graph import (
    AnalysisNode,
    ExperimentDesignNode,
    build_experiment_graph,
)


def test_build_experiment_graph():
    graph = build_experiment_graph()
    assert graph.name == "experiment"


def test_node_classes_exist():
    assert ExperimentDesignNode is not None
    assert AnalysisNode is not None
