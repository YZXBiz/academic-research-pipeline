"""ExperimentSubgraphNode must convert string figure paths into FigureArtifact.

The LLM-generated Dagster workspace writes results.json with figures as a
list of string paths. If those strings are dropped (filtered to only
FigureArtifact instances), the writing phase's VisualizationNode gets
an empty inventory and either invents figures or omits them entirely.
"""
from __future__ import annotations

import inspect
import re

from academic_pipeline.pipeline import nodes as pipeline_nodes


def test_experiment_subgraph_converts_string_figures_to_artifacts() -> None:
    """The conversion must happen — silent dropping of string paths is a
    correctness bug that leaves the paper without figures.

    Whitespace-tolerant regex matches both inline and multi-line constructor
    formatting so `ruff format` reflows don't break this test.
    """
    src = inspect.getsource(pipeline_nodes)
    assert re.search(r"FigureArtifact\s*\(\s*figure_type\s*=", src), (
        "ExperimentSubgraphNode must construct FigureArtifact instances from "
        "string figure paths — see pipeline/nodes.py around line 444."
    )
