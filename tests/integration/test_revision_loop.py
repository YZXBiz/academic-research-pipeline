"""Integration test: MergeReviews is terminal — no revision loops in research graph."""

from __future__ import annotations

import contextlib

import pytest
from pydantic_ai.models.test import TestModel

from academic_pipeline.core.enums import (
    EditorialDecision,
    IssueSeverity,
    ReviewDimension,
)
from academic_pipeline.models.ethics import EthicsChecklist
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
from tests.conftest import make_structured_test_model, make_test_deps


pytestmark = pytest.mark.anyio

_RESEARCH_MODEL_MAP: dict[str, type] = {
    "research_question": RQBrief,
    "research_architect": MethodologyBlueprint,
    "bibliography": Bibliography,
    "source_verification": SourceVerificationReport,
    "synthesis": SynthesisReport,
    "report_compiler": ResearchReport,
    "independent_verifier": IndependentVerificationReport,
    "editor_in_chief": EditorReview,
    "ethics_review": EthicsChecklist,
}

_ACCEPT_REVIEW = EditorReview(
    verdict=EditorialDecision.ACCEPT,
    weighted_score=4.5,
    dimensions=[EditorDimensionScore(dimension=d, score=4.5, weight=0.20, notes="Good") for d in ReviewDimension],
    issues=[],
    strengths=["Strong work"],
    summary="Accepted.",
)


def _override_research_agents(
    *,
    editor_review: EditorReview | None = None,
    text_output: str = "Test output.",
) -> contextlib.ExitStack:
    """Override research agents with structured output for editor."""
    text_model = TestModel(custom_output_text=text_output, call_tools=[])
    eic_json = (editor_review or _ACCEPT_REVIEW).model_dump_json()
    eic_model = TestModel(custom_output_text=eic_json, call_tools=[])
    stack = contextlib.ExitStack()
    for name, agent in _agents.items():
        if name == "editor_in_chief":
            stack.enter_context(agent.override(model=eic_model))
        elif name in _RESEARCH_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_RESEARCH_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=text_model))
    return stack


class TestMergeReviewsTerminal:
    """MergeReviews is now terminal — no backward routing regardless of EIC verdict."""

    async def test_accept_completes(self) -> None:
        state = ResearchState(topic="AI in education")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_research_agents():
            graph = build_research_graph()
            result = await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        assert result.output is not None

    async def test_major_revision_still_completes(self) -> None:
        """Even with MAJOR_REVISION, graph terminates — MergeReviews is terminal."""
        state = ResearchState(topic="AI in education")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        major_revision = EditorReview(
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

        with _override_research_agents(editor_review=major_revision):
            graph = build_research_graph()
            result = await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        assert result.output is not None
