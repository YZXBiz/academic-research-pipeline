"""TestModel-based proof that the visualization curator agent registers correctly.

Per CLAUDE.md: structured-output agents must work with
agent.override(model=TestModel(custom_output_text=json_text)). If the
YAML rewrite (commit 27755c7) breaks the agent's PromptedOutput wiring,
this catches it deterministically without hitting the real model.
"""
from __future__ import annotations

import json

import pytest
from pydantic_ai.models.test import TestModel


@pytest.mark.asyncio
async def test_visualization_agent_returns_figure_package_via_testmodel() -> None:
    from academic_pipeline.models.writing import FigurePackage
    from academic_pipeline.writing.agents import agents

    agent = agents["visualization"]
    fake_pkg = {
        "figures": [
            {
                "figure_number": 1,
                "caption": "Silhouette score vs k for K-means, Ward, and GMM (silhouette=0.137 at k=8).",
                "source_path": "/abs/figures/figure_01.png",
                "code": "",  # curator leaves code empty per the new spec
                "code_language": "python",
                "data_source": "",
                "placement": "",
            }
        ],
    }
    fake_text = json.dumps(fake_pkg)

    with agent.override(model=TestModel(custom_output_text=fake_text, call_tools=[])):
        result = await agent.run("dummy context — overridden by TestModel")

    assert isinstance(result.output, FigurePackage)
    assert len(result.output.figures) == 1
    fig = result.output.figures[0]
    assert fig.figure_number == 1
    assert fig.source_path is not None
    assert str(fig.source_path) == "/abs/figures/figure_01.png"
    assert fig.code == ""  # curator leaves code empty
