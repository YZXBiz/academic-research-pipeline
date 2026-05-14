"""Unit tests for PydanticAI writing graph nodes."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import AsyncMock, patch

import pydantic_core
import pytest
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData
from pydantic_graph import Graph, GraphRunContext


@pytest.fixture(autouse=True)
def _mock_doi_verification():
    """Stub ``verify_doi`` so the §6.7.T2 build gate does not hit doi.org.

    Writing-graph tests use placeholder DOIs like ``10.1234/test`` which
    would fail real CrossRef lookup; the gate would then abort the build
    with REN001. Patch the doi module's ``verify_doi`` symbol — that's where
    ``verify_dois_in_bibtex`` resolves it.
    """

    async def _ok(doi: str) -> str:
        return json.dumps({"doi": doi, "exists": True, "status": 200})

    with patch(
        "academic_pipeline.tools.bibliography.doi.verify_doi",
        new=AsyncMock(side_effect=_ok),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_authors_gate():
    """Stub the §6.7.T3 authors.yaml gate so writing-graph tests pass.

    Without this patch ``LatexCompilerNode`` would abort with REN002 before
    pandoc because no real ``authors.yaml`` is on disk. Patches both the
    resolver and the loader at the source module so the function-scoped
    imports inside ``LatexCompilerNode.run`` see the stubs.
    """
    from pathlib import Path as _Path

    from academic_pipeline.runtime.authors_yaml import AuthorsYamlEntry

    fake_path = _Path("authors.yaml")
    fake_entries = [AuthorsYamlEntry(name="Test User", affiliation="Test Lab")]
    with (
        patch(
            "academic_pipeline.runtime.authors_yaml.resolve_authors_yaml_path",
            return_value=fake_path,
        ),
        patch(
            "academic_pipeline.runtime.authors_yaml.load_authors_yaml",
            return_value=fake_entries,
        ),
    ):
        yield


from academic_pipeline.models.citation_grounding import CitationGroundingReport
from academic_pipeline.models.research import (
    Bibliography,
    PRISMACounts,
    SearchStrategy,
)
from academic_pipeline.models.review import (
    FigureVerificationReport,
    PeerReviewOutput,
)
from academic_pipeline.models.shared import Source
from academic_pipeline.models.writing import (
    AbstractOutput,
    ArgumentBlueprint,
    CitationAudit,
    FigurePackage,
    FormattedPaper,
    LiteratureStrategy,
    OutlineSection,
    PaperConfig,
    PaperDraft,
    PaperOutline,
    Section,
)
from academic_pipeline.writing.graph import (
    FormatterNode,
    ParallelSectionDraftNode,
    SectionMergerNode,
    SectionPlannerNode,
    _is_parent_section,
    build_writing_graph,
)
from academic_pipeline.writing.state import WritingState
from tests.conftest import json_for_model, make_test_deps


def _make_test_paper_draft() -> PaperDraft:
    """Construct a minimal valid PaperDraft for tests that need a non-None draft."""
    from academic_pipeline.models.shared import (
        Author,
        Reference,
    )

    return PaperDraft(
        title="Test",
        abstract="Test abstract.",
        authors=[Author(name="Test", affiliation="Test")],
        keywords=["k1", "k2", "k3"],
        sections=[Section(heading="Body", level=1, content="A draft.", word_count=2, citation_count=0)],
        references=[Reference(id="ref1", full_citation="Test (2024).")],
        total_word_count=2,
    )


def _make_test_bibliography() -> Bibliography:
    """Construct a minimal valid Bibliography for tests that need a non-None bib."""
    return Bibliography(
        sources=[
            Source(
                id="S1",
                title="Test Paper",
                authors=["Author A"],
                year=2024,
                doi="10.1234/test",
                citation="Author A. (2024). Test Paper.",
                type="journal_article",
                evidence_tier=2,
                quality_tier="tier_1",
                relevance="core",
                relevance_score=8,
                annotation="Test.",
                verified=True,
                retraction_check=True,
            )
        ],
        search_strategy=SearchStrategy(
            databases=["Exa"],
            keywords=["test"],
            inclusion_criteria=["relevant"],
            exclusion_criteria=["irrelevant"],
            date_range="2020-2025",
        ),
        coverage_assessment="Good.",
        minimum_sources=1,
        prisma_counts=PRISMACounts(identified=10, screened=8, eligible=5, included=3),
    )


def _make_minimal_outline() -> PaperOutline:
    return PaperOutline(
        title="Test",
        structure_type="IMRaD",
        total_word_count_target=5000,
        sections=[OutlineSection(title="Intro", word_count_target=1000, purpose="Introduce", content_summary="...")],
    )


def _make_minimal_blueprint() -> ArgumentBlueprint:
    return ArgumentBlueprint(central_thesis="AI improves education")


pytestmark = pytest.mark.anyio


def _make_agents_dict():
    """Import agents lazily so import errors surface clearly."""
    from academic_pipeline.writing.agents import agents

    return agents


# PromptedOutput agents need TestModel with custom_output_text containing valid JSON matching
# the model's schema.  Map each agent name to its output model class.
_STRUCTURED_AGENT_MODELS: dict[str, type] = {
    "intake": PaperConfig,
    "literature_strategist": LiteratureStrategy,
    "structure_architect": PaperOutline,
    "argument_builder": ArgumentBlueprint,
    "draft_writer": PaperDraft,
    "citation_compliance": CitationAudit,
    "abstract": AbstractOutput,
    "peer_reviewer": PeerReviewOutput,
    "formatter": FormattedPaper,
    "visualization": FigurePackage,
    "section_writer": Section,
    "figure_verifier": FigureVerificationReport,
    "citation_grounding": CitationGroundingReport,
}

_STRUCTURED_AGENTS = set(_STRUCTURED_AGENT_MODELS)


def _json_for_model_local(model_cls: type, seed: int = 0) -> str:
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


def _override_all(
    output: str = "Decision: Accept\n\nAll good.",
) -> contextlib.ExitStack:
    """Override every writing agent with a TestModel.

    Structured-output agents use PromptedOutput, so TestModel needs custom_output_text with valid JSON. String-output
    agents use custom_output_text with plain text.
    """
    agents = _make_agents_dict()
    text_model = TestModel(custom_output_text=output, call_tools=[])
    stack = contextlib.ExitStack()
    for name, agent in agents.items():
        if name in _STRUCTURED_AGENT_MODELS:
            model_cls = _STRUCTURED_AGENT_MODELS[name]
            json_text = json_for_model(model_cls)
            struct_model = TestModel(custom_output_text=json_text, call_tools=[])
            stack.enter_context(agent.override(model=struct_model))
        else:
            stack.enter_context(agent.override(model=text_model))
    return stack


def _all_node_classes() -> list[type]:
    """Import all node classes."""
    from academic_pipeline.writing.graph import (
        ArgumentBuilderNode,
        BibTexGeneratorNode,
        CitationComplianceNode,
        CitationGroundingNode,
        DraftWriterNode,
        FigureVerificationNode,
        FormatterNode,
        IntakeNode,
        LatexCompilerNode,
        LiteratureStrategistNode,
        MergePhase5Node,
        ParallelAbstractVizNode,
        ParallelSectionDraftNode,
        PeerReviewerNode,
        SectionMergerNode,
        SectionPlannerNode,
        StructureArchitectNode,
    )

    return [
        IntakeNode,
        LiteratureStrategistNode,
        StructureArchitectNode,
        ArgumentBuilderNode,
        SectionPlannerNode,
        ParallelSectionDraftNode,
        SectionMergerNode,
        DraftWriterNode,
        CitationComplianceNode,
        ParallelAbstractVizNode,
        MergePhase5Node,
        CitationGroundingNode,
        FigureVerificationNode,
        PeerReviewerNode,
        FormatterNode,
        BibTexGeneratorNode,
        LatexCompilerNode,
    ]


class TestIntakeNodeRouting:
    """IntakeNode routes based on bibliography presence."""

    async def test_with_bibliography_routes_to_lit_strategist(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode

        state = WritingState(
            topic="AI in education",
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all("Intake analysis complete."):
            graph = Graph(nodes=_all_node_classes())
            result = await graph.run(IntakeNode(), state=state, deps=deps)

        # Should have gone through lit strategist path and completed
        assert result.output is not None

    async def test_without_bibliography_skips_lit_strategist(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode

        state = WritingState(
            topic="AI in education",
            bibliography=None,
        )
        deps = make_test_deps()

        with _override_all("Decision: Accept\n\nAll good."):
            graph = Graph(nodes=_all_node_classes())
            result = await graph.run(IntakeNode(), state=state, deps=deps)

        # Should skip lit strategist and still complete
        assert result.output is not None


class TestPeerReviewerRouting:
    """PeerReviewerNode always routes to FormatterNode (no revision loop)."""

    async def test_always_routes_to_formatter(self) -> None:
        from academic_pipeline.writing.graph import PeerReviewerNode

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            paper_outline=_make_minimal_outline(),
            argument_blueprint=_make_minimal_blueprint(),
            peer_review_round=0,
        )
        deps = make_test_deps()

        with _override_all("Decision: Accept\n\nExcellent paper."):
            graph = Graph(nodes=_all_node_classes())
            result = await graph.run(PeerReviewerNode(), state=state, deps=deps)

        assert result.output is not None

    async def test_stores_review_in_state(self) -> None:
        from academic_pipeline.writing.graph import PeerReviewerNode

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            paper_outline=_make_minimal_outline(),
            argument_blueprint=_make_minimal_blueprint(),
        )
        deps = make_test_deps()

        with _override_all():
            node = PeerReviewerNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, FormatterNode)
        assert state.internal_review is not None
        assert len(state.messages) >= 1


class TestLinearNodes:
    """Test that linear nodes update state correctly."""

    async def test_draft_writer_updates_paper_draft(self) -> None:
        from academic_pipeline.writing.graph import DraftWriterNode

        state = WritingState(
            topic="AI in education",
            paper_outline=_make_minimal_outline(),
            argument_blueprint=_make_minimal_blueprint(),
        )
        deps = make_test_deps()

        with _override_all("Decision: Accept\n\nA complete draft."):
            graph = Graph(nodes=_all_node_classes())
            await graph.run(DraftWriterNode(), state=state, deps=deps)

        assert state.paper_draft != {}
        assert len(state.messages) >= 1

    async def test_citation_compliance_updates_audit(self) -> None:
        from academic_pipeline.writing.graph import (
            CitationComplianceNode,
        )

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all("Citation audit complete. All citations valid."):
            graph = Graph(nodes=_all_node_classes())
            await graph.run(CitationComplianceNode(), state=state, deps=deps)

        assert state.citation_audit != {}
        assert len(state.messages) >= 1


class TestCitationGroundingNode:
    """CitationGroundingNode semantically verifies each citation against its source."""

    async def test_merge_phase5_routes_to_citation_grounding(self) -> None:
        """MergePhase5Node must hand off to CitationGroundingNode, not straight to figures."""
        from academic_pipeline.writing.graph import (
            CitationGroundingNode,
            MergePhase5Node,
        )

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all():
            node = MergePhase5Node()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, CitationGroundingNode)

    async def test_citation_grounding_routes_to_figure_verification(self) -> None:
        from academic_pipeline.writing.graph import (
            CitationGroundingNode,
            FigureVerificationNode,
        )

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all():
            node = CitationGroundingNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, FigureVerificationNode)

    async def test_citation_grounding_populates_state(self) -> None:
        """After running, state.citation_grounding holds a CitationGroundingReport.

        Uses a draft that actually cites a source the bibliography contains —
        otherwise the node correctly skips (nothing to ground).
        """
        from academic_pipeline.models.citation_grounding import CitationGroundingReport
        from academic_pipeline.models.shared import Author, Reference
        from academic_pipeline.models.writing import PaperDraft, Section
        from academic_pipeline.writing.graph import CitationGroundingNode

        cited_draft = PaperDraft(
            title="Test",
            abstract="Test abstract.",
            authors=[Author(name="Test", affiliation="Test")],
            keywords=["k1", "k2", "k3"],
            sections=[
                Section(
                    heading="Introduction",
                    level=1,
                    content="Prior work establishes the baseline [@S1].",
                    word_count=6,
                    citation_count=1,
                ),
            ],
            references=[Reference(id="ref1", full_citation="Test (2024).")],
            total_word_count=6,
        )
        state = WritingState(
            topic="AI in education",
            paper_draft=cited_draft,
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all():
            node = CitationGroundingNode()
            await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(state.citation_grounding, CitationGroundingReport)
        assert len(state.messages) >= 1

    async def test_citation_grounding_skips_gracefully_without_bibliography(self) -> None:
        """No bibliography = nothing to ground against. Route forward, don't crash."""
        from academic_pipeline.writing.graph import (
            CitationGroundingNode,
            FigureVerificationNode,
        )

        state = WritingState(
            topic="AI in education",
            paper_draft=_make_test_paper_draft(),
            bibliography=None,
        )
        deps = make_test_deps()

        with _override_all():
            node = CitationGroundingNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, FigureVerificationNode)
        assert state.citation_grounding is None


class TestSectionPlannerNode:
    async def test_produces_section_specs(self) -> None:
        outline = PaperOutline(
            title="AI Ethics",
            structure_type="IMRaD",
            total_word_count_target=5000,
            sections=[
                OutlineSection(
                    title="Introduction",
                    word_count_target=1000,
                    purpose="Introduce topic",
                    content_summary="Overview of AI ethics",
                ),
                OutlineSection(
                    title="Methods",
                    word_count_target=2000,
                    purpose="Describe methods",
                    content_summary="Survey methodology",
                ),
                OutlineSection(
                    title="Results",
                    word_count_target=1500,
                    purpose="Present findings",
                    content_summary="Key findings",
                ),
            ],
        )
        blueprint = ArgumentBlueprint(central_thesis="AI needs ethical governance")
        state = WritingState(
            topic="AI Ethics",
            paper_outline=outline,
            argument_blueprint=blueprint,
        )
        deps = make_test_deps()

        with _override_all():
            node = SectionPlannerNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, ParallelSectionDraftNode)
        assert len(state.section_specs) == 3
        assert state.section_specs[0].heading == "Introduction"
        assert state.section_specs[1].heading == "Methods"
        assert state.section_specs[2].heading == "Results"
        # Check adjacent context
        assert "Next section:" in state.section_specs[0].adjacent_context
        assert "Previous section:" in state.section_specs[1].adjacent_context

    async def test_empty_outline_produces_no_specs(self) -> None:
        outline = PaperOutline(
            title="Empty",
            structure_type="IMRaD",
            total_word_count_target=0,
            sections=[],
        )
        blueprint = ArgumentBlueprint(central_thesis="Thesis")
        state = WritingState(
            topic="Empty topic",
            paper_outline=outline,
            argument_blueprint=blueprint,
        )
        deps = make_test_deps()

        with _override_all():
            node = SectionPlannerNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, ParallelSectionDraftNode)
        assert len(state.section_specs) == 0


class TestParallelSectionDraftNode:
    async def test_drafts_sections_concurrently(self) -> None:
        from academic_pipeline.models.writing import SectionSpec

        state = WritingState(
            topic="AI Ethics",
            section_specs=[
                SectionSpec(
                    heading="Introduction",
                    level=1,
                    word_count_target=1000,
                    purpose="Introduce",
                    content_guidance="Overview",
                ),
                SectionSpec(
                    heading="Methods",
                    level=1,
                    word_count_target=2000,
                    purpose="Methods",
                    content_guidance="Survey",
                ),
            ],
        )
        deps = make_test_deps()

        with _override_all():
            node = ParallelSectionDraftNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, SectionMergerNode)
        assert len(state.section_drafts) == 2

    async def test_empty_specs_produces_no_drafts(self) -> None:
        state = WritingState(topic="Empty", section_specs=[])
        deps = make_test_deps()

        with _override_all():
            node = ParallelSectionDraftNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, SectionMergerNode)
        assert len(state.section_drafts) == 0


class TestSectionMergerNode:
    async def test_merges_sections_into_draft(self) -> None:
        from academic_pipeline.models.writing import (
            PaperDraft,
            Section,
        )

        outline = PaperOutline(
            title="AI Ethics",
            structure_type="IMRaD",
            total_word_count_target=5000,
        )
        sections = [
            Section(heading="Intro", level=1, content="Introduction content here.", word_count=100, citation_count=2),
            Section(heading="Methods", level=1, content="Methods content here.", word_count=200, citation_count=3),
        ]
        state = WritingState(
            topic="AI Ethics",
            paper_outline=outline,
            section_drafts=sections,
        )
        deps = make_test_deps()

        with _override_all():
            from academic_pipeline.writing.graph import CitationComplianceNode

            node = SectionMergerNode()
            next_node = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(next_node, CitationComplianceNode)
        assert state.paper_draft is not None
        assert isinstance(state.paper_draft, PaperDraft)
        assert state.paper_draft.title == "AI Ethics"
        assert state.paper_draft.total_word_count == 300
        assert len(state.paper_draft.sections) == 2


class TestSectionNodes:
    def test_new_nodes_in_graph(self) -> None:
        graph = build_writing_graph()
        node_names = list(graph.node_defs.keys())
        assert "SectionPlannerNode" in node_names
        assert "ParallelSectionDraftNode" in node_names
        assert "SectionMergerNode" in node_names

    def test_draft_writer_still_in_graph(self) -> None:
        """DraftWriterNode must remain as a node in the writing graph."""
        graph = build_writing_graph()
        node_names = list(graph.node_defs.keys())
        assert "DraftWriterNode" in node_names

    def test_regression_checkpoint_removed(self) -> None:
        """RegressionCheckpointNode has been removed — per-node eval replaces it."""
        graph = build_writing_graph()
        node_names = list(graph.node_defs.keys())
        assert "RegressionCheckpointNode" not in node_names


class TestIsParentSection:
    def test_parent_with_numbered_children(self):
        headings = ["4. Challenges", "4.1 Oracle Problem", "4.2 Data Quality", "5. Conclusion"]
        assert _is_parent_section("4. Challenges", headings) is True

    def test_child_is_not_parent(self):
        headings = ["4. Challenges", "4.1 Oracle Problem", "4.2 Data Quality"]
        assert _is_parent_section("4.1 Oracle Problem", headings) is False

    def test_section_without_children(self):
        headings = ["1. Introduction", "2. Background", "3. Methods"]
        assert _is_parent_section("1. Introduction", headings) is False

    def test_parent_without_dot(self):
        headings = ["4 Challenges", "4.1 Oracle Problem", "4.2 Data Quality"]
        assert _is_parent_section("4 Challenges", headings) is True

    def test_parent_with_section_prefix(self):
        headings = ["Section 4: Challenges", "4.1 Oracle Problem"]
        assert _is_parent_section("Section 4: Challenges", headings) is True

    def test_non_numbered_heading(self):
        headings = ["Introduction", "Background"]
        assert _is_parent_section("Introduction", headings) is False
