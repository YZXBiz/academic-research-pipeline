"""PydanticAI pipeline orchestrator graph builder.

Imports all node classes from nodes.py and wires them into a single Graph.
"""

from __future__ import annotations

from pydantic_graph import Graph

from academic_pipeline.pipeline.nodes import ALL_NODES


def build_pipeline_graph() -> Graph:
    """Build the pipeline orchestrator graph with all 11 nodes."""
    return Graph(name="pipeline", nodes=ALL_NODES)  # pyright: ignore[reportReturnType]
