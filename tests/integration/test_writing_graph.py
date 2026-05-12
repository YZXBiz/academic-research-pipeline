"""Integration tests for the PydanticAI writing subgraph."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import AsyncMock, patch

import pydantic_core
import pytest
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData
from pydantic_graph.persistence.in_mem import SimpleStatePersistence


@pytest.fixture(autouse=True)
def _mock_doi_verification():
    """Stub ``verify_doi`` so the §6.7.T2 build gate does not hit doi.org.

    Integration tests use placeholder DOIs like ``10.1234/test`` which would
    fail real CrossRef lookup; the gate would then abort the writing graph
    with REN001. Patching at the doi module level (where
    ``verify_dois_in_bibtex`` resolves the symbol) makes every DOI verify
    successfully for the life of the test.
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

    The integration suite runs the writing graph end-to-end without a real
    ``authors.yaml`` on disk; without this patch ``LatexCompilerNode``
    would abort with REN002 before pandoc. Patches both the resolver and
    the loader at the source module so the function-scoped imports inside
    ``LatexCompilerNode.run`` see the stubs.
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
    PaperConfig,
    PaperDraft,
    PaperOutline,
    Section,
)
from academic_pipeline.writing.state import WritingState
from tests.conftest import make_test_deps


pytestmark = pytest.mark.anyio


def _json_for_model(model_cls: type, seed: int = 0) -> str:
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


# Map each structured agent to its output model class.
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
}


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


def _override_all_agents(output: str = "Decision: Accept\n\nAll good.") -> contextlib.ExitStack:
    """Override every writing agent with a TestModel that skips tool calls."""
    from academic_pipeline.writing.agents import agents

    stack = contextlib.ExitStack()
    for name, agent in agents.items():
        if name in _STRUCTURED_AGENT_MODELS:
            json_text = _json_for_model(_STRUCTURED_AGENT_MODELS[name])
            model = TestModel(custom_output_text=json_text, call_tools=[])
        else:
            # text-only agents (revision_coach)
            model = TestModel(custom_output_text=output, call_tools=[])
        stack.enter_context(agent.override(model=model))
    return stack


class TestWritingGraphCompletion:
    """Test that the writing graph runs end-to-end."""

    async def test_graph_runs_to_completion(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode, build_writing_graph

        graph = build_writing_graph()
        state = WritingState(
            topic="AI in education",
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nAll looks good."):
            result = await graph.run(IntakeNode(), state=state, deps=deps)

        assert result.output is not None
        assert len(result.output) > 0

    async def test_graph_without_bibliography(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode, build_writing_graph

        graph = build_writing_graph()
        state = WritingState(topic="AI in education", bibliography=None)
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nPaper complete."):
            result = await graph.run(IntakeNode(), state=state, deps=deps)

        assert result.output is not None

    async def test_graph_with_persistence(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode, build_writing_graph

        graph = build_writing_graph()
        state = WritingState(
            topic="Machine learning in healthcare",
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()
        persistence = SimpleStatePersistence()

        with _override_all_agents("Decision: Accept\n\nNo issues."):
            result = await graph.run(
                IntakeNode(),
                state=state,
                deps=deps,
                persistence=persistence,
            )

        assert result.output is not None


class TestWritingGraphState:
    """Test that state is properly populated after graph execution."""

    async def test_state_populated_after_full_run(self) -> None:
        from academic_pipeline.writing.graph import IntakeNode, build_writing_graph

        graph = build_writing_graph()
        state = WritingState(
            topic="Quantum computing applications",
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nExcellent work."):
            await graph.run(IntakeNode(), state=state, deps=deps)

        # Core state fields should be populated after a full run
        assert state.paper_outline != {}
        assert state.argument_blueprint != {}
        assert state.paper_draft != {}
        assert state.citation_audit != {}
        assert state.abstract_result != {}
        # Messages should have accumulated from all nodes
        assert len(state.messages) >= 6


class TestWritingGraphPeerReviewLoop:
    """Test peer review runs through the full graph (single-pass, no revision loop)."""

    async def test_peer_review_executes(self) -> None:
        from academic_pipeline.writing.agents import agents as _agents
        from academic_pipeline.writing.graph import IntakeNode, build_writing_graph

        graph = build_writing_graph()
        state = WritingState(
            topic="Educational technology",
            bibliography=_make_test_bibliography(),
        )
        deps = make_test_deps()

        # peer_reviewer returns Major Revision (structured) — per-node eval replaces
        # the old revision loop, so the graph completes in a single pass.
        import json

        revision_json = json.dumps(
            {
                "decision": "Major Revision",
                "overall_score": 5.0,
                "dimension_scores": {
                    "originality": 5,
                    "methodological_rigor": 5,
                    "evidence_sufficiency": 5,
                    "argument_coherence": 5,
                    "writing_quality": 5,
                },
                "summary": "Needs significant work.",
                "report": "Details.",
            }
        )
        revision_model = TestModel(custom_output_text=revision_json, call_tools=[])

        with contextlib.ExitStack() as stack:
            for name, agent in _agents.items():
                if name == "peer_reviewer":
                    stack.enter_context(agent.override(model=revision_model))
                elif name in _STRUCTURED_AGENT_MODELS:
                    json_text = _json_for_model(_STRUCTURED_AGENT_MODELS[name])
                    model = TestModel(custom_output_text=json_text, call_tools=[])
                    stack.enter_context(agent.override(model=model))
                else:
                    text_model = TestModel(custom_output_text="Decision: Accept\n\nAll good.", call_tools=[])
                    stack.enter_context(agent.override(model=text_model))

            result = await graph.run(IntakeNode(), state=state, deps=deps)

        # Graph should complete successfully; peer review is single-pass
        assert result.output is not None
        assert state.internal_review is not None


class TestWritingGraphNodes:
    """Test graph construction includes all expected nodes."""

    def test_graph_has_all_nodes(self) -> None:
        from academic_pipeline.writing.graph import build_writing_graph

        graph = build_writing_graph()
        assert graph is not None
