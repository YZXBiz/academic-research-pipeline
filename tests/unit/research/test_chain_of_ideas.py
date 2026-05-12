"""Tests for the Chain-of-Ideas models, agents, state, and node behaviour.

Spec 2 Phase 1 (see ``docs/superpowers/specs/2026-05-03-chain-of-ideas-kg-design.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from academic_pipeline.config import DEFAULT_CONFIG, PipelineConfig
from academic_pipeline.models.chain import (
    ChainEdge,
    DevelopmentChain,
    EdgeRelation,
    Milestone,
    MilestoneType,
    ThesisStatement,
)
from academic_pipeline.research.state import ResearchState


def _make_milestone(idx: int = 1) -> Milestone:
    return Milestone(
        milestone_id=f"M{idx}",
        milestone_type=MilestoneType.CONCEPT_INTRO,
        year=2020 + idx,
        key_paper_doi=f"10.0000/m{idx}",
        key_paper_title=f"Milestone {idx} paper",
        one_sentence_advance=f"Advance {idx}.",
    )


def _make_chain() -> DevelopmentChain:
    milestones = [_make_milestone(i) for i in range(1, 6)]
    edges = [
        ChainEdge(
            from_milestone=f"M{i}",
            to_milestone=f"M{i + 1}",
            relation=EdgeRelation.EXTENDS,
        )
        for i in range(1, 5)
    ]
    return DevelopmentChain(
        milestones=milestones,
        edges=edges,
        terminal_unsolved_problem="Unresolved gap that motivates new work.",
    )


# ---------- Models ----------


def test_milestone_is_frozen() -> None:
    from pydantic import ValidationError

    m = _make_milestone()
    with pytest.raises(ValidationError):  # pydantic raises ValidationError on assignment
        m.year = 1999  # type: ignore[misc]


def test_development_chain_round_trip_json() -> None:
    chain = _make_chain()
    text = chain.model_dump_json()
    restored = DevelopmentChain.model_validate_json(text)
    assert restored == chain
    assert len(restored.milestones) == 5
    assert restored.edges[0].relation == EdgeRelation.EXTENDS


def test_thesis_statement_accepts_allowed_novelty_dimension() -> None:
    t = ThesisStatement(
        claim="X improves Y by 12% on benchmark B.",
        novelty_dimension="method_extension",
        grounded_in_milestone="M5",
    )
    assert t.novelty_dimension == "method_extension"


def test_thesis_statement_rejects_unknown_novelty_dimension() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ThesisStatement(
            claim="X improves Y.",
            novelty_dimension="bogus",  # type: ignore[arg-type]
            grounded_in_milestone="M1",
        )


def test_milestone_type_and_edge_relation_str_values() -> None:
    assert MilestoneType.CONCEPT_INTRO.value == "concept_intro"
    assert EdgeRelation.SUPERSEDES.value == "supersedes"


# ---------- Config flag ----------


def test_chain_of_ideas_flag_default_on() -> None:
    """PRD §6.1.T1 — Phase 4 flips chain_of_ideas_enabled default from False to True.
    Chain-of-Ideas + thesis extractor become the canonical research path.
    """
    cfg = PipelineConfig()
    assert cfg.chain_of_ideas_enabled is True
    assert DEFAULT_CONFIG.chain_of_ideas_enabled is True


def test_legacy_knowledge_graph_escape_hatch_default_off() -> None:
    """PRD §6.1.T1 — legacy_knowledge_graph escape hatch defaults to False.

    Operators set this true to keep the legacy KnowledgeGraphNode running once
    §6.1.T2 wires the Phase 4 graph topology (CoI canonical, KG legacy-only).
    """
    cfg = PipelineConfig()
    assert cfg.legacy_knowledge_graph is False
    assert DEFAULT_CONFIG.legacy_knowledge_graph is False


# ---------- ResearchState wiring ----------


def test_research_state_has_chain_and_thesis_fields() -> None:
    s = ResearchState()
    assert s.chain is None
    assert s.thesis is None


def test_research_state_can_hold_chain_and_thesis() -> None:
    chain = _make_chain()
    thesis = ThesisStatement(
        claim="X improves Y by 5%.",
        novelty_dimension="new_application",
        grounded_in_milestone="M3",
    )
    s = ResearchState(chain=chain, thesis=thesis)
    assert s.chain is chain
    assert s.thesis is thesis


# ---------- YAML specs load ----------


def test_chain_of_ideas_extractor_yaml_loads() -> None:
    from pydantic_ai import Agent

    spec = Path("src/academic_pipeline/research/specs/chain_of_ideas_extractor.yaml")
    agent = Agent.from_file(spec)
    assert agent is not None


def test_thesis_extractor_yaml_loads() -> None:
    from pydantic_ai import Agent

    spec = Path("src/academic_pipeline/research/specs/thesis_extractor.yaml")
    agent = Agent.from_file(spec)
    assert agent is not None


def test_chain_of_ideas_extractor_yaml_mentions_5_to_15_constraint() -> None:
    text = Path("src/academic_pipeline/research/specs/chain_of_ideas_extractor.yaml").read_text()
    # The 5-15 milestone constraint must be explicit so the model honours it.
    assert "5" in text
    assert "15" in text
    # Must also reference the bibliography grounding requirement.
    assert "bibliography" in text.lower()


# ---------- Node behaviour ----------


@dataclass
class _StubDeps:
    """Minimal deps stub for ChainOfIdeasNode flag-off path."""

    config: Any = field(default_factory=PipelineConfig)


@dataclass
class _StubCtx:
    """Minimal GraphRunContext substitute (only state + deps are read)."""

    state: ResearchState
    deps: _StubDeps


@pytest.mark.asyncio()
async def test_chain_of_ideas_node_skips_when_flag_off() -> None:
    """Flag-off path: PRD §6.1.T3 reorder makes ChainOfIdeasNode pass through to
    SynthesisNode (was: ReportCompilerNode pre-T3). The skip preserves both
    state.chain and state.thesis as None for SynthesisNode's flag-off branch
    (which falls back to bibliography-only validate_state)."""
    from academic_pipeline.research.graph import (
        ChainOfIdeasNode,
        SynthesisNode,
    )

    state = ResearchState(topic="x")
    deps = _StubDeps(config=PipelineConfig(chain_of_ideas_enabled=False))
    node = ChainOfIdeasNode()

    result = await node.run(_StubCtx(state=state, deps=deps))  # type: ignore[arg-type]

    assert isinstance(result, SynthesisNode)
    assert state.chain is None
    assert state.thesis is None


def test_research_graph_includes_chain_of_ideas_node() -> None:
    """The build_research_graph nodes list must include ChainOfIdeasNode
    between SynthesisNode and ReportCompilerNode so its routing is reachable."""
    from academic_pipeline.research import graph as rg

    g = rg.build_research_graph()
    # Graph stores nodes by class name in node_defs; check both ways.
    node_names = set(g.node_defs.keys())
    assert "ChainOfIdeasNode" in node_names
    assert "ReportCompilerNode" in node_names
    assert "SynthesisNode" in node_names


def test_synthesis_node_returns_report_compiler_post_t3() -> None:
    """Static check: PRD §6.1.T3 reorder — SynthesisNode now returns
    ReportCompilerNode (was: ChainOfIdeasNode pre-T3)."""
    import typing

    from academic_pipeline.research.graph import (
        ReportCompilerNode,
        SynthesisNode,
    )

    hints = typing.get_type_hints(SynthesisNode.run)
    assert hints["return"] is ReportCompilerNode


# ---------- PRD §6.1.T3: Phase 4 topology — CoI runs BEFORE Synthesis ----------


def test_chain_of_ideas_node_returns_synthesis_node_after_t3_reorder() -> None:
    """PRD §6.1.T3 — Phase 4 reorder: ChainOfIdeasNode now routes to SynthesisNode
    (was: ReportCompilerNode). Synthesis becomes thesis-anchored."""
    import typing

    from academic_pipeline.research.graph import (
        ChainOfIdeasNode,
    )

    hints = typing.get_type_hints(ChainOfIdeasNode.run)
    # Returns SynthesisNode under default flag, ReportCompilerNode under flag-off
    # (legacy pre-CoI no-op pass-through still routes through). Union allowed.
    return_type = hints["return"]
    # Must include SynthesisNode in the return type union
    return_type_str = str(return_type)
    assert "SynthesisNode" in return_type_str, (
        f"ChainOfIdeasNode.run must route to SynthesisNode after §6.1.T3 "
        f"(thesis-required-input wiring). Got: {return_type_str}"
    )


def test_synthesis_node_returns_report_compiler_node_after_t3_reorder() -> None:
    """PRD §6.1.T3 — Phase 4 reorder: SynthesisNode now routes directly to
    ReportCompilerNode (was: ChainOfIdeasNode). The CoI/Thesis extraction has
    already happened upstream."""
    import typing

    from academic_pipeline.research.graph import (
        ReportCompilerNode,
        SynthesisNode,
    )

    hints = typing.get_type_hints(SynthesisNode.run)
    assert hints["return"] is ReportCompilerNode, (
        f"SynthesisNode.run must route to ReportCompilerNode after §6.1.T3. " f"Got: {hints['return']}"
    )


def test_rubric_synthesis_includes_thesis_advancement_dimension() -> None:
    """PRD §6.1.T4 — _RUBRIC_SYNTHESIS must include a "Thesis advancement"
    dimension so the per-node evaluator scores synthesis on whether it
    advances the thesis (not just on coherence/evidence/depth)."""
    from academic_pipeline.research.graph import _RUBRIC_SYNTHESIS

    assert "Thesis advancement" in _RUBRIC_SYNTHESIS, (
        "_RUBRIC_SYNTHESIS must list 'Thesis advancement' as a scored "
        f"dimension after PRD §6.1.T4. Current rubric:\n{_RUBRIC_SYNTHESIS}"
    )
    # Must be a numeric scoring dimension matching the existing pattern
    assert "Thesis advancement (0-10)" in _RUBRIC_SYNTHESIS, (
        "Thesis advancement must follow the (0-10) scoring convention used "
        "by the other dimensions in _RUBRIC_SYNTHESIS."
    )


def test_synthesis_agent_has_output_validator_for_thesis() -> None:
    """PRD §6.1.T3 — synthesis agent has at least one output_validator registered.

    PydanticAI registers output_validators in the agent's internal collection.
    Defense in depth on the SynthesisReport structure."""
    from academic_pipeline.research.agents import agents

    synthesis = agents["synthesis"]
    # PydanticAI exposes registered validators via _output_validators (private API)
    # or output_validators (public-ish). Cover both shapes.
    validators = getattr(synthesis, "_output_validators", None) or getattr(synthesis, "output_validators", None) or []
    assert len(list(validators)) >= 1, "synthesis agent must have at least one output_validator after §6.1.T3"


# ---------- PRD §6.1.T6: EthicsReviewNode + EthicsReviewOutput deleted ----------


def test_ethics_review_node_deleted_from_research_graph() -> None:
    """PRD §6.1.T6 — EthicsReviewNode is gone from research/graph.py.
    The integrity subgraph's EthicsChecklistNode (PRD §6.5.T1) is the canonical
    ethics path now."""
    from academic_pipeline.research import graph as rg

    assert not hasattr(
        rg, "EthicsReviewNode"
    ), "EthicsReviewNode must be deleted from research/graph.py per PRD §6.1.T6"


def test_ethics_review_output_model_deleted() -> None:
    """PRD §6.1.T6 — EthicsReviewOutput Pydantic class is gone (orphan after
    EthicsChecklist replaced it as the agent's output type)."""
    from academic_pipeline.models import research as research_models

    assert not hasattr(
        research_models, "EthicsReviewOutput"
    ), "EthicsReviewOutput must be deleted from models/research.py per PRD §6.1.T6"


def test_research_graph_excludes_ethics_review_node() -> None:
    """PRD §6.1.T6 — build_research_graph must not include EthicsReviewNode."""
    from academic_pipeline.research import graph as rg

    g = rg.build_research_graph()
    assert "EthicsReviewNode" not in g.node_defs, "build_research_graph must exclude EthicsReviewNode after §6.1.T6"


def test_editor_in_chief_routes_to_merge_reviews_after_t6() -> None:
    """PRD §6.1.T6 — with EthicsReviewNode deleted, EditorInChiefNode routes
    directly to MergeReviewsNode (was: EthicsReviewNode)."""
    import typing

    from academic_pipeline.research.graph import EditorInChiefNode, MergeReviewsNode

    hints = typing.get_type_hints(EditorInChiefNode.run)
    assert hints["return"] is MergeReviewsNode, (
        f"EditorInChiefNode.run must route to MergeReviewsNode after §6.1.T6. " f"Got: {hints['return']}"
    )


# ---------- PRD §6.1.T7: KnowledgeGraphNode + KG models deleted ----------


def test_knowledge_graph_node_deleted_from_research_graph() -> None:
    """PRD §6.1.T7 — KnowledgeGraphNode is gone from research/graph.py.
    The §6.1.T2 escape hatch (legacy_knowledge_graph flag) becomes a no-op
    since the canonical Phase-4 path runs CoI + thesis-anchored synthesis."""
    from academic_pipeline.research import graph as rg

    assert not hasattr(
        rg, "KnowledgeGraphNode"
    ), "KnowledgeGraphNode must be deleted from research/graph.py per PRD §6.1.T7"


def test_knowledge_graph_pydantic_models_deleted() -> None:
    """PRD §6.1.T7 — KnowledgeGraph + SourceRelationship + ResearchCluster
    Pydantic classes are deleted (orphan after KG node removal)."""
    from academic_pipeline.models import research as research_models

    for cls in ("KnowledgeGraph", "SourceRelationship", "ResearchCluster"):
        assert not hasattr(research_models, cls), f"{cls} must be deleted from models/research.py per PRD §6.1.T7"


def test_research_graph_excludes_knowledge_graph_node() -> None:
    """PRD §6.1.T7 — build_research_graph must not include KnowledgeGraphNode."""
    from academic_pipeline.research import graph as rg

    g = rg.build_research_graph()
    assert "KnowledgeGraphNode" not in g.node_defs, "build_research_graph must exclude KnowledgeGraphNode after §6.1.T7"


def test_research_state_drops_knowledge_graph_field() -> None:
    """PRD §6.1.T7 — ResearchState.knowledge_graph field is removed
    (orphan after KG node + model deletion)."""
    state = ResearchState()
    assert not hasattr(state, "knowledge_graph"), "ResearchState.knowledge_graph field must be removed per PRD §6.1.T7"
