"""Integration tests for the PydanticAI research subgraph."""

from __future__ import annotations

import contextlib

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_graph.persistence.in_mem import SimpleStatePersistence

from academic_pipeline.core.enums import (
    EditorialDecision,
    IssueSeverity,
    ReviewDimension,
)
from academic_pipeline.models.research import (
    Bibliography,
    IndependentVerificationReport,
    MethodologyBlueprint,
    ResearchReport,
    RQBrief,
    SourceVerificationReport,
    SynthesisReport,
)
from academic_pipeline.models.review import (
    EditorDimensionScore,
    EditorReview,
    ReviewIssue,
)
from academic_pipeline.research.agents import agents as _agents
from academic_pipeline.research.graph import (
    ResearchQuestionNode,
    build_research_graph,
)
from academic_pipeline.research.state import ResearchState
from tests.conftest import json_for_model, make_structured_test_model, make_test_deps  # noqa: F401


pytestmark = pytest.mark.anyio

# Map every structured-output research agent to its Pydantic model class.
_STRUCTURED_AGENT_MODELS: dict[str, type] = {
    "research_question": RQBrief,
    "research_architect": MethodologyBlueprint,
    "bibliography": Bibliography,
    "source_verification": SourceVerificationReport,
    "synthesis": SynthesisReport,
    "report_compiler": ResearchReport,
    "independent_verifier": IndependentVerificationReport,
    "editor_in_chief": EditorReview,
    # PRD §6.1.T6 — ethics_review agent moved to integrity.agents.
}

_DEFAULT_EDITOR_ACCEPT = EditorReview(
    verdict=EditorialDecision.ACCEPT,
    weighted_score=4.5,
    dimensions=[],
    issues=[],
    strengths=["Strong work"],
    summary="Verdict: PASS\n\nAll good.",
)


def _override_all_agents(
    output: str = "Verdict: PASS\n\nAll good.",
    *,
    editor_review: EditorReview | None = None,
) -> contextlib.ExitStack:
    """Override every research agent with appropriate TestModel.

    PromptedOutput agents need custom_output_text with valid JSON.
    The editor_in_chief agent gets a specific EditorReview instance serialized.
    """
    text_model = TestModel(custom_output_text=output, call_tools=[])
    eic_json = (editor_review or _DEFAULT_EDITOR_ACCEPT).model_dump_json()
    eic_model = TestModel(custom_output_text=eic_json, call_tools=[])
    stack = contextlib.ExitStack()
    for name, agent in _agents.items():
        if name == "editor_in_chief":
            stack.enter_context(agent.override(model=eic_model))
        elif name in _STRUCTURED_AGENT_MODELS:
            # Prefer FIXTURE_INSTANCES (e.g., EthicsChecklist needs a fixture
            # that satisfies its output_validator) and fall back to schema-based
            # JSON generation otherwise.
            model = make_structured_test_model(_STRUCTURED_AGENT_MODELS[name])
            stack.enter_context(agent.override(model=model))
        else:
            stack.enter_context(agent.override(model=text_model))
    return stack


class TestResearchGraphCompletion:
    """Test that the research graph runs end-to-end."""

    async def test_graph_runs_to_completion(self) -> None:
        graph = build_research_graph()
        state = ResearchState(topic="AI in education")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all_agents("Verdict: PASS\n\nAll looks good."):
            result = await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        assert result.output is not None
        assert len(result.output) > 0

    async def test_graph_with_persistence(self) -> None:
        graph = build_research_graph()
        state = ResearchState(topic="Machine learning in healthcare")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})
        persistence = SimpleStatePersistence()

        with _override_all_agents("Verdict: PASS\n\nNo issues."):
            result = await graph.run(
                ResearchQuestionNode(),
                state=state,
                deps=deps,
                persistence=persistence,
            )

        assert result.output is not None


class TestResearchGraphState:
    """Test that state is properly populated after graph execution."""

    async def test_state_populated_after_full_run(self) -> None:
        graph = build_research_graph()
        state = ResearchState(topic="Quantum computing applications")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all_agents("Verdict: PASS\n\nExcellent work."):
            await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        # Core state fields should be populated after a full run
        assert state.rq_brief != {}
        assert state.methodology_blueprint != {}
        assert state.bibliography != {}
        assert state.synthesis != {}
        assert state.review_report != {}
        assert state.eic_review != ""
        # Messages should have accumulated from all nodes
        assert len(state.messages) >= 6

    async def test_ethics_review_node_absent_from_research_graph(self) -> None:
        """PRD §6.1.T6 — research subgraph no longer runs ethics review.
        The 12-item PRISMA-trAIce ethics checklist runs in the integrity
        subgraph (`EthicsChecklistNode` per §6.5.T1). This is the
        replacement for the deleted `test_blocked_ethics_ends_early`."""
        graph = build_research_graph()
        node_names = set(graph.node_defs.keys())
        assert "EthicsReviewNode" not in node_names
        assert "ethics_review" not in _agents


class TestResearchGraphNoBackwardTraversal:
    """MergeReviewsNode is terminal -- no backward routing regardless of EIC verdict."""

    async def test_major_revision_eic_still_ends(self) -> None:
        graph = build_research_graph()
        state = ResearchState(topic="Educational technology")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        major_revision_review = EditorReview(
            verdict=EditorialDecision.MAJOR_REVISION,
            weighted_score=2.5,
            dimensions=[
                EditorDimensionScore(dimension=ReviewDimension.ORIGINALITY, score=4.0, weight=0.20, notes="OK"),
                EditorDimensionScore(dimension=ReviewDimension.METHODOLOGY, score=2.0, weight=0.25, notes="Weak"),
                EditorDimensionScore(dimension=ReviewDimension.EVIDENCE, score=3.5, weight=0.25, notes="OK"),
                EditorDimensionScore(dimension=ReviewDimension.COHERENCE, score=4.0, weight=0.15, notes="OK"),
                EditorDimensionScore(dimension=ReviewDimension.WRITING, score=3.5, weight=0.15, notes="OK"),
            ],
            issues=[
                ReviewIssue(
                    severity=IssueSeverity.CRITICAL,
                    dimension=ReviewDimension.METHODOLOGY,
                    description="No integration protocol",
                    recommendation="Add one",
                )
            ],
            strengths=["Good lit review"],
            summary="Needs methodology work.",
        )

        with _override_all_agents(editor_review=major_revision_review):
            result = await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        # Graph completes — MergeReviews is terminal, no backward routing
        assert result.output is not None


class TestResearchGraphZeroCycle:
    """The research graph runs in a single forward pass with no cycles."""

    async def test_research_graph_runs_without_backward_traversal(self) -> None:
        state = ResearchState(topic="AI in higher education assessment")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all_agents():
            graph = build_research_graph()
            result = await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        assert result.output is not None
        assert state.rq_brief is not None
        assert state.methodology_blueprint is not None
        assert state.bibliography is not None
        assert state.synthesis is not None


class TestResearchGraphNodes:
    """Test graph construction includes all expected nodes."""

    def test_graph_has_12_nodes(self) -> None:
        # Was 11; ChainOfIdeasNode added in Spec 2 Phase 1 (2026-05-04).
        graph = build_research_graph()
        assert graph is not None
        assert len(graph.node_defs) == 12

    def test_graph_has_no_da_nodes(self) -> None:
        graph = build_research_graph()
        assert "DACheckpoint1Node" not in graph.node_defs
        assert "DACheckpoint2Node" not in graph.node_defs
