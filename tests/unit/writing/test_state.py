"""Tests for WritingState dataclass."""

from __future__ import annotations

import pytest

from academic_pipeline.writing.state import WritingState
from tests.unit.core.test_serialization import (
    _make_bibliography,
    _make_rq_brief,
    _make_synthesis,
)


def _make_paper_draft():
    """Create a minimal PaperDraft for testing."""
    from academic_pipeline.models.shared import (
        Author,
        Reference,
    )
    from academic_pipeline.models.writing import (
        PaperDraft,
        Section,
    )

    return PaperDraft(
        title="Test",
        abstract="Abstract text",
        authors=[Author(name="Smith", affiliation="MIT")],
        keywords=["ml", "education", "outcomes"],
        sections=[Section(heading="Intro", level=1, content="Draft text here", word_count=100, citation_count=2)],
        references=[Reference(id="r1", full_citation="Smith (2024)")],
        total_word_count=100,
    )


def _make_paper_outline():
    """Create a minimal PaperOutline for testing."""
    from academic_pipeline.models.writing import (
        OutlineSection,
        PaperOutline,
    )

    return PaperOutline(
        title="Test Outline",
        structure_type="IMRaD",
        sections=[
            OutlineSection(
                title="Intro",
                word_count_target=500,
                purpose="Introduce topic",
                content_summary="Overview",
            ),
        ],
        total_word_count_target=5000,
    )


def _make_argument_blueprint():
    """Create a minimal ArgumentBlueprint for testing."""
    from academic_pipeline.models.writing import ArgumentBlueprint

    return ArgumentBlueprint(central_thesis="ML improves outcomes")


def _make_figure_package():
    """Create a minimal FigurePackage for testing."""
    from academic_pipeline.models.writing import FigurePackage

    return FigurePackage()


def _make_style_profile():
    """Create a minimal StyleProfile for testing."""
    from academic_pipeline.models.writing import (
        CitationStyleMetrics,
        ParagraphLength,
        SentenceLength,
        StyleProfile,
        VocabularyPreferences,
    )

    return StyleProfile(
        calibration_source=["sample.txt"],
        sample_count=1,
        sentence_length=SentenceLength(mean=15.0, stddev=5.0),
        paragraph_length=ParagraphLength(mean_sentences=4.0),
        vocabulary_preferences=VocabularyPreferences(),
        citation_style=CitationStyleMetrics(narrative_ratio=0.4, parenthetical_ratio=0.6, density=2.0),
    )


def _make_response_to_reviewers():
    """Create a minimal ResponseToReviewers for testing."""
    from academic_pipeline.models.review import (
        ResponseItem,
        ResponseToReviewers,
    )

    return ResponseToReviewers(
        revision_round=1,
        items=[
            ResponseItem(
                roadmap_item_id="item1",
                reviewer_comment="Fix methods",
                author_response="Fixed",
                change_location="Section 3",
                status="RESOLVED",
            )
        ],
    )


def _make_revision_roadmap():
    """Create a minimal RevisionRoadmap for testing."""
    from academic_pipeline.models.review import RevisionRoadmap

    return RevisionRoadmap(
        items=[],
        total_items=0,
        must_fix_count=0,
        editorial_decision="Minor Revision",
        consensus_summary="Reviewers agree",
    )


class TestWritingState:
    def test_default_construction(self) -> None:
        state = WritingState()
        assert state.topic == ""
        assert state.rq_brief is None
        assert state.bibliography is None
        assert state.synthesis is None
        assert state.paper_draft is None
        assert state.paper_config is None
        assert state.paper_outline is None
        assert state.argument_blueprint is None
        assert state.figure_package is None
        assert state.response_to_reviewers is None
        assert state.revision_roadmap == {}
        assert state.style_profile is None
        assert state.review_report == {}
        assert state.messages == []
        assert state.internal_review == ""
        assert state.citation_audit == {}
        assert state.abstract_result == {}
        assert state.score_history == []
        assert state.score_trajectory_flags == []
        assert state.needs_revision is False

    def test_construction_with_all_fields(self) -> None:
        rq = _make_rq_brief()
        bib = _make_bibliography()
        syn = _make_synthesis()
        draft = _make_paper_draft()
        outline = _make_paper_outline()
        blueprint = _make_argument_blueprint()
        figs = _make_figure_package()
        rtr = _make_response_to_reviewers()
        style = _make_style_profile()
        state = WritingState(
            topic="machine learning in education",
            rq_brief=rq,
            bibliography=bib,
            synthesis=syn,
            paper_draft=draft,
            paper_outline=outline,
            argument_blueprint=blueprint,
            figure_package=figs,
            response_to_reviewers=rtr,
            revision_roadmap={"items": [], "total_items": 0},
            style_profile=style,
            review_report={"score": 7.5},
            messages=[{"role": "user", "content": "write a paper"}],
            internal_review="looks good",
            citation_audit={"raw": "3 orphans found"},
            abstract_result={"raw": "Abstract text"},
            needs_revision=True,
        )
        assert state.topic == "machine learning in education"
        assert state.rq_brief is not None
        assert state.rq_brief.research_question == "What is X?"
        assert state.paper_draft is not None
        assert state.paper_draft.title == "Test"
        assert state.needs_revision is True
        assert state.internal_review == "looks good"
        assert state.citation_audit == {"raw": "3 orphans found"}
        assert state.abstract_result == {"raw": "Abstract text"}

    def test_messages_independent(self) -> None:
        s1 = WritingState()
        s2 = WritingState()
        s1.messages.append({"role": "user", "content": "hi"})
        assert s2.messages == []

    def test_mutable_defaults_independent(self) -> None:
        """Verify dict defaults use default_factory (no shared state).

        Typed model fields default to None and are immutable frozen models,
        so they are excluded from this test.
        """
        s1 = WritingState()
        s2 = WritingState()
        s1.review_report["key"] = "value"
        assert s2.review_report == {}

    def test_score_trajectory_fields_independent(self) -> None:
        """Verify score_history and score_trajectory_flags use default_factory."""
        s1 = WritingState()
        s2 = WritingState()
        s1.score_history.append({"overall": 75})
        s1.score_trajectory_flags.append("regression")
        assert s2.score_history == []
        assert s2.score_trajectory_flags == []

    def test_field_mutation(self) -> None:
        """Verify mutable fields can be updated in place."""
        state = WritingState()
        state.messages.append({"role": "system", "content": "init"})
        state.needs_revision = True
        assert len(state.messages) == 1
        assert state.needs_revision is True


# PRD §6.1.T8 — chain + thesis handoff from research → writing.


class TestChainThesisHandoff:
    def test_chain_field_exists_and_defaults_to_none(self) -> None:
        """PRD §6.1.T8 — WritingState.chain field exists, typed
        DevelopmentChain | None, defaults to None."""
        state = WritingState()
        assert hasattr(state, "chain")
        assert state.chain is None

    def test_thesis_field_exists_and_defaults_to_none(self) -> None:
        """PRD §6.1.T8 — WritingState.thesis field exists, typed
        ThesisStatement | None, defaults to None."""
        state = WritingState()
        assert hasattr(state, "thesis")
        assert state.thesis is None

    def test_chain_and_thesis_round_trip_through_construction(self) -> None:
        """Both fields accept real DevelopmentChain + ThesisStatement values."""
        from academic_pipeline.models.chain import (
            ChainEdge,
            DevelopmentChain,
            EdgeRelation,
            Milestone,
            MilestoneType,
            ThesisStatement,
        )

        milestones = [
            Milestone(
                milestone_id=f"M{i}",
                milestone_type=MilestoneType.CONCEPT_INTRO,
                year=2020 + i,
                key_paper_doi=f"10.0/m{i}",
                key_paper_title=f"M{i} title",
                one_sentence_advance=f"Advance {i}.",
            )
            for i in range(1, 6)
        ]
        edges = [
            ChainEdge(from_milestone=f"M{i}", to_milestone=f"M{i + 1}", relation=EdgeRelation.EXTENDS)
            for i in range(1, 5)
        ]
        chain = DevelopmentChain(milestones=milestones, edges=edges, terminal_unsolved_problem="Unresolved gap.")
        thesis = ThesisStatement(
            claim="X improves Y by 5%.", novelty_dimension="new_application", grounded_in_milestone="M3"
        )

        state = WritingState(chain=chain, thesis=thesis)
        assert state.chain is chain
        assert state.thesis is thesis


# PRD §6.1.T8 — WritePhaseNode wires chain + thesis from PipelineState into WritingState.


@pytest.mark.anyio()
async def test_write_phase_node_forwards_chain_and_thesis_to_writing_state() -> None:
    """PRD §6.1.T8 — When ResearchPhaseNode populated PipelineState.chain +
    .thesis, WritePhaseNode must forward both into the WritingState it builds."""
    import contextlib
    from unittest.mock import AsyncMock, patch

    from pydantic_graph import GraphRunContext

    from academic_pipeline.models.chain import (
        ChainEdge,
        DevelopmentChain,
        EdgeRelation,
        Milestone,
        MilestoneType,
        ThesisStatement,
    )
    from academic_pipeline.pipeline.nodes import WritePhaseNode
    from academic_pipeline.pipeline.state import PipelineState
    from tests.conftest import make_test_deps

    chain = DevelopmentChain(
        milestones=[
            Milestone(
                milestone_id=f"M{i}",
                milestone_type=MilestoneType.CONCEPT_INTRO,
                year=2020 + i,
                key_paper_doi=f"10.0/m{i}",
                key_paper_title=f"M{i}",
                one_sentence_advance=f"Advance {i}.",
            )
            for i in range(1, 6)
        ],
        edges=[
            ChainEdge(from_milestone=f"M{i}", to_milestone=f"M{i + 1}", relation=EdgeRelation.EXTENDS)
            for i in range(1, 5)
        ],
        terminal_unsolved_problem="Gap.",
    )
    thesis = ThesisStatement(
        claim="X improves Y.",
        novelty_dimension="new_application",
        grounded_in_milestone="M3",
    )

    # Capture the WritingState passed to the inner subgraph runner so we can
    # assert chain + thesis flowed through.
    captured: dict[str, WritingState] = {}

    async def _capture_subgraph(
        graph,
        start_node,
        writing_state,
        deps,
        **_kwargs,
    ):
        captured["state"] = writing_state
        return writing_state  # bypass actual subgraph run

    state = PipelineState(topic="t", chain=chain, thesis=thesis)
    deps = make_test_deps()

    with (
        patch(
            "academic_pipeline.pipeline.nodes._run_subgraph_with_persistence",
            new=_capture_subgraph,
        ),
        patch(
            "academic_pipeline.traceability.copilot.copilot_checkpoint",
            new=AsyncMock(return_value=None),
        ),
        contextlib.suppress(
            Exception
        ),  # downstream merge ops may fail on stub state — fine, we only care about pre-merge wiring
    ):
        node = WritePhaseNode()
        await node.run(GraphRunContext(state=state, deps=deps))

    assert "state" in captured, "WritePhaseNode must invoke the writing subgraph"
    assert captured["state"].chain is chain, "WritingState.chain must be forwarded from PipelineState.chain"
    assert captured["state"].thesis is thesis, "WritingState.thesis must be forwarded from PipelineState.thesis"
