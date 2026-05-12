"""Tests for NoveltyGateNode (SCI Spec 3 Phase 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_graph import End, GraphRunContext

from academic_pipeline.core.enums import PipelineStatus
from academic_pipeline.models.novelty_gate import NoveltyGateResult
from academic_pipeline.pipeline.nodes import (
    NoveltyGateNode,
    ResearchPhaseNode,
)
from academic_pipeline.pipeline.state import PipelineState
from tests.conftest import make_test_deps


pytestmark = pytest.mark.asyncio


async def test_node_passes_through_when_flag_off() -> None:
    """When novelty_gate_enabled=False, return ResearchPhaseNode without calling S2."""
    state = PipelineState(topic="any topic")
    deps = make_test_deps()
    assert deps.config.novelty_gate_enabled is False

    target = "academic_pipeline.research.novelty_gate.compute_novelty_gate"
    with patch(target, new=AsyncMock()) as mock_compute:
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    mock_compute.assert_not_called()
    assert isinstance(result, ResearchPhaseNode)
    assert state.novelty_gate_result is None


async def test_node_returns_end_on_redundant_verdict() -> None:
    """REDUNDANT verdict aborts the run with End."""
    state = PipelineState(topic="redundant topic")
    deps = make_test_deps()
    deps.config.novelty_gate_enabled = True

    canned = NoveltyGateResult(
        verdict="redundant",
        max_similarity=0.97,
        nearest_neighbors=[],
        note="REDUNDANT: too close to existing work",
    )

    target = "academic_pipeline.research.novelty_gate.compute_novelty_gate"
    with patch(target, new=AsyncMock(return_value=canned)):
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    assert isinstance(result, End)
    assert "BLOCKED by novelty gate" in result.data
    assert state.novelty_gate_result is canned
    assert state.pipeline_status == PipelineStatus.ABORTED
    # Operator-visible message recorded for the dashboard
    assert any("Novelty gate" in m.get("content", "") for m in state.messages)


async def test_node_proceeds_on_novel_verdict() -> None:
    """NOVEL verdict sets state and routes to ResearchPhaseNode."""
    state = PipelineState(topic="genuinely new topic")
    deps = make_test_deps()
    deps.config.novelty_gate_enabled = True

    canned = NoveltyGateResult(
        verdict="novel",
        max_similarity=0.20,
        nearest_neighbors=[],
        note="NOVEL: low similarity",
    )

    target = "academic_pipeline.research.novelty_gate.compute_novelty_gate"
    with patch(target, new=AsyncMock(return_value=canned)):
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    assert isinstance(result, ResearchPhaseNode)
    assert state.novelty_gate_result is canned
    assert state.pipeline_status != PipelineStatus.ABORTED


async def test_node_proceeds_on_partial_verdict() -> None:
    """PARTIAL verdict (Phase 1) passes through to ResearchPhaseNode with state set."""
    state = PipelineState(topic="kinda close topic")
    deps = make_test_deps()
    deps.config.novelty_gate_enabled = True

    canned = NoveltyGateResult(
        verdict="partial",
        max_similarity=0.85,
        nearest_neighbors=[],
        note="PARTIAL: differentiation needed",
    )

    target = "academic_pipeline.research.novelty_gate.compute_novelty_gate"
    with patch(target, new=AsyncMock(return_value=canned)):
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    assert isinstance(result, ResearchPhaseNode)
    assert state.novelty_gate_result is canned
    assert state.novelty_gate_result.verdict == "partial"
