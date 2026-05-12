"""Unit tests for PydanticAI review graph nodes."""

from __future__ import annotations

import contextlib

import pydantic_core
import pytest
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData
from pydantic_graph import Graph

from academic_pipeline.core.enums import EditorialDecision
from academic_pipeline.models.review import (
    EditorialSynthesis,
    EICReview,
    FieldAnalysis,
    PeerReviewReport,
)
from academic_pipeline.review.agents import REVIEWER_AGENTS
from academic_pipeline.review.agents import agents as _agents
from academic_pipeline.review.graph import (
    CascadedReviewNode,
    EditorialSynthesizerNode,
    FieldAnalystNode,
    ParallelReviewerNode,
    PointWiseNoveltyReviewerNode,
    RevisionCoachingNode,
)
from academic_pipeline.review.state import ReviewState
from tests.conftest import make_test_deps


pytestmark = pytest.mark.anyio

ALL_REVIEW_NODES = [
    FieldAnalystNode,
    ParallelReviewerNode,
    PointWiseNoveltyReviewerNode,
    CascadedReviewNode,
    EditorialSynthesizerNode,
    RevisionCoachingNode,
]


def _json_for_model(model_cls: type, seed: int = 0) -> str:
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


# PromptedOutput agents need custom_output_text with valid JSON matching the model schema.
_AGENT_MODEL_MAP: dict[str, type | None] = {
    "field_analyst": FieldAnalysis,
    "eic": EICReview,
    "methodology_reviewer": PeerReviewReport,
    "domain_reviewer": PeerReviewReport,
    "perspective_reviewer": PeerReviewReport,
    "editorial_synthesizer": EditorialSynthesis,
}


def _override_all(output: str = "Decision: Accept\n\nAll good.") -> contextlib.ExitStack:
    """Override every review agent with a TestModel."""
    stack = contextlib.ExitStack()
    for name, agent in _agents.items():
        model_cls = _AGENT_MODEL_MAP.get(name)
        if model_cls is not None:
            model = TestModel(custom_output_text=_json_for_model(model_cls), call_tools=[])
        else:
            model = TestModel(custom_output_text=output, call_tools=[])
        stack.enter_context(agent.override(model=model))
    return stack


class TestParallelReviewerNode:
    """ParallelReviewerNode dispatches all reviewers concurrently."""

    async def test_all_reviewers_run_in_parallel(self) -> None:
        """All three reviewers should produce reports in a single node step."""
        state = ReviewState(paper_draft={"title": "Test", "content": "A test paper about AI."})
        deps = make_test_deps()

        with _override_all("This paper has solid methodology."):
            graph = Graph(nodes=ALL_REVIEW_NODES)
            node = ParallelReviewerNode()
            await graph.run(node, state=state, deps=deps)

        # All three reviewers should have contributed reports
        assert len(state.reviewer_reports) == len(REVIEWER_AGENTS)
        reviewer_ids = [r["reviewer_id"] for r in state.reviewer_reports]
        expected_ids = [rid for rid, _ in REVIEWER_AGENTS]
        assert set(reviewer_ids) == set(expected_ids)

    async def test_reports_contain_agent_keys(self) -> None:
        """Each report should include the agent key used."""
        state = ReviewState(paper_draft={"title": "Test", "content": "A test paper about AI."})
        deps = make_test_deps()

        with _override_all("Decision: Accept\n\nGreat paper."):
            graph = Graph(nodes=ALL_REVIEW_NODES)
            node = ParallelReviewerNode()
            await graph.run(node, state=state, deps=deps)

        expected_agents = {agent for _, agent in REVIEWER_AGENTS}
        actual_agents = {r["agent"] for r in state.reviewer_reports}
        assert actual_agents == expected_agents


class TestEditorialSynthesizerRouting:
    """EditorialSynthesizerNode routes based on editorial decision."""

    async def test_structured_output_sets_decision(self) -> None:
        """EditorialSynthesizer with structured output should set editorial_decision."""
        state = ReviewState(
            paper_draft={"title": "Test", "content": "A test paper."},
            reviewer_reports=[
                {"reviewer_id": "reviewer_1", "report": "Good methodology."},
                {"reviewer_id": "reviewer_2", "report": "Strong domain knowledge."},
                {"reviewer_id": "reviewer_3", "report": "Novel perspective."},
            ],
        )
        deps = make_test_deps()

        # TestModel auto-generates EditorialSynthesis with default string fields.
        # The auto-generated `decision` won't match the decision_map, so it
        # falls back to MAJOR_REVISION and routes through coaching.
        with _override_all():
            graph = Graph(nodes=ALL_REVIEW_NODES)
            result = await graph.run(EditorialSynthesizerNode(), state=state, deps=deps)

        assert state.editorial_decision is not None
        assert state.editorial_decision in (
            EditorialDecision.ACCEPT,
            EditorialDecision.MINOR_REVISION,
            EditorialDecision.MAJOR_REVISION,
            EditorialDecision.REJECT,
        )
        assert result.output is not None


