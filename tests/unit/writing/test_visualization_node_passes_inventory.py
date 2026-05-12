"""ParallelAbstractVizNode._run_visualization must inject available_figures.

Without an inventory in the context, the curator agent (post the
visualization.yaml rewrite) has nothing to pick from and falls back to
inventing specs. This test inspects the source to ensure the wiring
is in place.
"""
from __future__ import annotations

import inspect
import re

from academic_pipeline.writing import graph as wg


def test_parallel_abstract_viz_node_references_experiment_figures() -> None:
    """The node must read ctx.state.experiment_figures and inject paths
    into the agent context."""
    src = inspect.getsource(wg.ParallelAbstractVizNode)
    assert "experiment_figures" in src, (
        "ParallelAbstractVizNode.run() (specifically its _run_visualization "
        "helper) must read ctx.state.experiment_figures to build the "
        "available_figures inventory for the curator."
    )


def test_parallel_abstract_viz_node_uses_available_figures_label() -> None:
    """The injected context must use the 'available_figures' label so it
    matches what the curator's instructions reference."""
    src = inspect.getsource(wg.ParallelAbstractVizNode)
    # Whitespace-tolerant match to survive ruff format reflows.
    assert re.search(r"available_figures", src), (
        "ParallelAbstractVizNode must label the inventory as "
        "'available_figures' (matches the curator's visualization.yaml "
        "instructions)."
    )
