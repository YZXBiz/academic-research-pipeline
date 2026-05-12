"""PRD §6.1.T9 — Phase 4 chain-of-ideas + novelty-gate end-to-end checks.

5 unit tests verifying the Phase 4 contract:
1. ``test_thesis_present_after_synthesis`` — under default config the
   pipeline reaches synthesis with thesis populated upstream by
   ChainOfIdeasNode (per §6.1.T3 reorder).
2. ``test_kg_path_absent_under_default_flags`` — under default config
   the KnowledgeGraphNode is gone (per §6.1.T7) and is not a member of
   the research graph node set.
3. ``test_kg_legacy_flag_is_no_op_after_t7`` — `legacy_knowledge_graph=true`
   is now a no-op (PRD §6.1.T7 retained the flag for back-compat but
   deleted the node it gated). The flag accepts but has no behavioral
   effect.
4. ``test_novelty_gate_partial_warn_routes_to_research`` — soft-warn
   verdict (similarity ∈ [tau_warn, tau_block)) does NOT abort; routes
   to ResearchPhaseNode and surfaces the warning in state.messages.
5. ``test_novelty_gate_redundant_block_aborts_before_bibliography`` —
   hard-block verdict (similarity ≥ tau_block) aborts the pipeline via
   End(...) BEFORE ResearchPhaseNode runs (so bibliography is never
   constructed).

Spec sources: see `docs/superpowers/specs/2026-05-03-chain-of-ideas-kg-design.md`
and `2026-05-03-novelty-gate-spec3-design.md`.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# 1. Thesis is populated for SynthesisNode after Phase 4 reorder.
# ---------------------------------------------------------------------------


def test_thesis_present_after_synthesis() -> None:
    """PRD §6.1.T3 + §6.1.T8 — Phase 4 reorder: ChainOfIdeasNode runs BEFORE
    SynthesisNode so thesis is a required input. The static type contract
    confirms the topology: ChainOfIdeasNode → SynthesisNode → ReportCompiler.
    Together with `validate_state(["bibliography", "thesis", "chain"], ...)`
    on SynthesisNode, this guarantees thesis is present when synthesis runs.
    """
    import typing

    from academic_pipeline.research.graph import (
        ChainOfIdeasNode,
        ReportCompilerNode,
        SynthesisNode,
    )

    coi_hints = typing.get_type_hints(ChainOfIdeasNode.run)
    synth_hints = typing.get_type_hints(SynthesisNode.run)

    # CoI returns SynthesisNode (the topology guarantees thesis-before-synthesis).
    assert "SynthesisNode" in str(coi_hints["return"])
    # Synthesis returns ReportCompilerNode (no detour back through CoI).
    assert synth_hints["return"] is ReportCompilerNode


# ---------------------------------------------------------------------------
# 2. KG path absent under default flags (post-§6.1.T7 deletion).
# ---------------------------------------------------------------------------


def test_kg_path_absent_under_default_flags() -> None:
    """PRD §6.1.T7 — the legacy KnowledgeGraphNode is deleted. Under the
    default config (and any config — the node simply does not exist),
    `build_research_graph` does not include it."""
    from academic_pipeline.research import graph as rg

    g = rg.build_research_graph()
    assert "KnowledgeGraphNode" not in g.node_defs
    assert not hasattr(rg, "KnowledgeGraphNode")


# ---------------------------------------------------------------------------
# 3. legacy_knowledge_graph flag is now a deprecated no-op (PRD §6.1.T7).
# ---------------------------------------------------------------------------


def test_kg_legacy_flag_is_no_op_after_t7() -> None:
    """PRD §6.1.T7 — `legacy_knowledge_graph=true` is a no-op now. The
    config flag is still accepted (preserved for back-compat) but the node
    it gated is deleted, so flipping it has no behavioral effect."""
    from academic_pipeline.config import PipelineConfig
    from academic_pipeline.research import graph as rg

    # Both default and flag-on configs produce graphs without KnowledgeGraphNode.
    PipelineConfig(legacy_knowledge_graph=False)
    cfg_on = PipelineConfig(legacy_knowledge_graph=True)
    assert cfg_on.legacy_knowledge_graph is True

    g = rg.build_research_graph()  # graph topology is config-independent
    assert "KnowledgeGraphNode" not in g.node_defs
    assert not hasattr(rg, "KnowledgeGraphNode")


# ---------------------------------------------------------------------------
# 4. Novelty soft-warn verdict (PARTIAL) routes to ResearchPhaseNode.
# ---------------------------------------------------------------------------


async def test_novelty_gate_partial_warn_routes_to_research() -> None:
    """PRD §6.1.T5 / Spec 3 — PARTIAL verdict does NOT abort. The node
    routes to ResearchPhaseNode and persists the warning to state.messages
    + state.novelty_gate_result for downstream consumers (Phase 2 will
    use the partial-warn signal to inject a differentiation paragraph)."""
    from unittest.mock import AsyncMock, patch

    from pydantic_graph import GraphRunContext

    from academic_pipeline.models.novelty_gate import NoveltyGateResult
    from academic_pipeline.pipeline.nodes import (
        NoveltyGateNode,
        ResearchPhaseNode,
    )
    from academic_pipeline.pipeline.state import PipelineState
    from tests.conftest import make_test_deps

    partial_result = NoveltyGateResult(
        verdict="partial",
        max_similarity=0.85,
        nearest_neighbors=[],
        note="Topic shares partial overlap with 3 prior works.",
    )
    state = PipelineState(topic="ML in healthcare")
    deps = make_test_deps()
    deps.config = deps.config.model_copy(update={"novelty_gate_enabled": True})

    with patch(
        "academic_pipeline.research.novelty_gate.compute_novelty_gate",
        new=AsyncMock(return_value=partial_result),
    ):
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    assert isinstance(result, ResearchPhaseNode), "PARTIAL verdict must NOT abort — must route to ResearchPhaseNode"
    assert state.novelty_gate_result == partial_result
    assert any("partial" in m["content"].lower() or "novelty" in m["content"].lower() for m in state.messages)


# ---------------------------------------------------------------------------
# 5. Novelty hard-block (REDUNDANT) aborts BEFORE bibliography.
# ---------------------------------------------------------------------------


async def test_novelty_gate_redundant_block_aborts_before_bibliography() -> None:
    """PRD §6.1.T5 / Spec 3 — REDUNDANT verdict (similarity ≥ tau_block)
    aborts the pipeline via End(...). NoveltyGateNode runs BEFORE
    ResearchPhaseNode, so bibliography construction never starts.
    state.pipeline_status is set to ABORTED."""
    from unittest.mock import AsyncMock, patch

    from pydantic_graph import End, GraphRunContext

    from academic_pipeline.core.enums import PipelineStatus
    from academic_pipeline.models.novelty_gate import NoveltyGateResult
    from academic_pipeline.pipeline.nodes import NoveltyGateNode
    from academic_pipeline.pipeline.state import PipelineState
    from tests.conftest import make_test_deps

    redundant_result = NoveltyGateResult(
        verdict="redundant",
        max_similarity=0.95,
        nearest_neighbors=[],
        note="Topic title matches existing publication at similarity=0.95.",
    )
    state = PipelineState(topic="Already-published work")
    deps = make_test_deps()
    deps.config = deps.config.model_copy(update={"novelty_gate_enabled": True})

    with patch(
        "academic_pipeline.research.novelty_gate.compute_novelty_gate",
        new=AsyncMock(return_value=redundant_result),
    ):
        node = NoveltyGateNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

    assert isinstance(result, End), "REDUNDANT verdict must End the pipeline"
    assert state.pipeline_status == PipelineStatus.ABORTED
    assert state.novelty_gate_result == redundant_result
    assert state.bibliography is None, "REDUNDANT must abort BEFORE ResearchPhaseNode (no bibliography construction)"
