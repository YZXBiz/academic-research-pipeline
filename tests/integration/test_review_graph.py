"""Integration tests for the PydanticAI review subgraph."""

from __future__ import annotations

import contextlib

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_graph.persistence.in_mem import SimpleStatePersistence

from academic_pipeline.models.review import (
    EICReview,
    EditorialSynthesis,
    FieldAnalysis,
    PeerReviewReport,
)
from academic_pipeline.review.agents import REVIEWER_AGENTS
from academic_pipeline.review.agents import agents as _agents
from academic_pipeline.review.graph import (
    FieldAnalystNode,
    build_review_graph,
)
from academic_pipeline.review.state import ReviewState
from academic_pipeline.core.enums import EditorialDecision
from tests.conftest import json_for_model, make_structured_test_model_with_overrides, make_test_deps


pytestmark = pytest.mark.anyio


# Map every structured-output review agent to its Pydantic model class.
_STRUCTURED_AGENT_MODELS: dict[str, type] = {
    "field_analyst": FieldAnalysis,
    "eic": EICReview,
    "methodology_reviewer": PeerReviewReport,
    "domain_reviewer": PeerReviewReport,
    "perspective_reviewer": PeerReviewReport,
    "editorial_synthesizer": EditorialSynthesis,
}


def _override_all_agents(
    output: str = "Decision: Accept\n\nAll good.",
    *,
    editorial_decision: str = "Accept",
) -> contextlib.ExitStack:
    """Override every review agent with a TestModel that skips tool calls."""
    text_model = TestModel(custom_output_text=output, call_tools=[])
    editorial_model = make_structured_test_model_with_overrides(
        EditorialSynthesis,
        {"decision": editorial_decision, "summary": output, "report": output},
    )
    stack = contextlib.ExitStack()
    for name, agent in _agents.items():
        if name == "editorial_synthesizer":
            stack.enter_context(agent.override(model=editorial_model))
        elif name in _STRUCTURED_AGENT_MODELS:
            model = TestModel(custom_output_text=json_for_model(_STRUCTURED_AGENT_MODELS[name]), call_tools=[])
            stack.enter_context(agent.override(model=model))
        else:
            stack.enter_context(agent.override(model=text_model))
    return stack


class TestReviewGraphCompletion:
    """Test that the review graph runs end-to-end."""

    async def test_graph_runs_to_completion_accept(self) -> None:
        """Full graph run with Accept decision reaches End."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A well-written paper about AI in education."})
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nExcellent work."):
            result = await graph.run(FieldAnalystNode(), state=state, deps=deps)

        assert result.output is not None
        assert len(result.output) > 0
        # All 3 reviewers should have filed reports
        assert len(state.reviewer_reports) == len(REVIEWER_AGENTS)
        # Editorial decision should be captured
        assert state.editorial_decision == EditorialDecision.ACCEPT
        # Messages should have accumulated from all nodes
        assert len(state.messages) >= 5

    async def test_graph_runs_to_completion_with_coaching(self) -> None:
        """Major Revision triggers coaching before End."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A paper needing revisions."})
        deps = make_test_deps()

        # Synthesizer returns Major Revision (structured output), all others generic text
        pass_model = TestModel(custom_output_text="Review output.", call_tools=[])
        revision_model = make_structured_test_model_with_overrides(
            EditorialSynthesis,
            {"decision": "Major Revision", "summary": "Needs significant work.", "report": "Details."},
        )

        with contextlib.ExitStack() as stack:
            for name, agent in _agents.items():
                if name == "editorial_synthesizer":
                    stack.enter_context(agent.override(model=revision_model))
                elif name in _STRUCTURED_AGENT_MODELS:
                    model = TestModel(custom_output_text=json_for_model(_STRUCTURED_AGENT_MODELS[name]), call_tools=[])
                    stack.enter_context(agent.override(model=model))
                else:
                    stack.enter_context(agent.override(model=pass_model))

            result = await graph.run(FieldAnalystNode(), state=state, deps=deps)

        assert result.output is not None
        assert state.editorial_decision == EditorialDecision.MAJOR_REVISION
        assert state.needs_coaching is True
        # Revision roadmap should be populated by coaching node
        assert state.revision_roadmap != {}

    async def test_graph_with_persistence(self) -> None:
        """Graph runs with SimpleStatePersistence."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A paper for persistence testing."})
        deps = make_test_deps()
        persistence = SimpleStatePersistence()

        with _override_all_agents("Decision: Accept\n\nGood paper."):
            result = await graph.run(
                FieldAnalystNode(),
                state=state,
                deps=deps,
                persistence=persistence,
            )

        assert result.output is not None


class TestReviewGraphState:
    """Test that state is properly populated after graph execution."""

    async def test_editorial_decision_captured_in_state(self) -> None:
        """Editorial decision should be set on state after full run."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A comprehensive research paper."})
        deps = make_test_deps()

        minor_model = make_structured_test_model_with_overrides(
            EditorialSynthesis,
            {"decision": "Minor Revision", "summary": "Small fixes needed.", "report": "Details."},
        )

        with _override_all_agents() as stack:
            stack.enter_context(_agents["editorial_synthesizer"].override(model=minor_model))
            result = await graph.run(FieldAnalystNode(), state=state, deps=deps)

        assert state.editorial_decision == EditorialDecision.MINOR_REVISION
        assert state.needs_coaching is True
        assert result.output is not None

    async def test_reviewer_reports_populated(self) -> None:
        """All reviewer reports should be present after full run."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A paper on quantum computing."})
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nStrong paper."):
            await graph.run(FieldAnalystNode(), state=state, deps=deps)

        assert len(state.reviewer_reports) == len(REVIEWER_AGENTS)
        for i, (expected_id, expected_agent) in enumerate(REVIEWER_AGENTS):
            assert state.reviewer_reports[i]["reviewer_id"] == expected_id
            assert state.reviewer_reports[i]["agent"] == expected_agent

    async def test_passes_through_during_run(self) -> None:
        """FieldAnalystNode should route directly to ParallelReviewerNode."""
        graph = build_review_graph()
        state = ReviewState(paper_draft={"title": "Test", "content": "A paper for checkpoint testing."})
        deps = make_test_deps()

        with _override_all_agents("Decision: Accept\n\nAll good."):
            await graph.run(FieldAnalystNode(), state=state, deps=deps)

        assert state.editorial_decision is not None
