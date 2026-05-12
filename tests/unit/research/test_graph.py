"""Unit tests for PydanticAI research graph nodes."""

from __future__ import annotations

import contextlib

import pydantic_core
import pytest
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData
from pydantic_graph import Graph

from academic_pipeline.core.enums import Verdict
from academic_pipeline.models.chain import DevelopmentChain, ThesisStatement
from academic_pipeline.models.ethics import EthicsChecklist
from academic_pipeline.models.research import (
    AnalyticalFramework,
    Bibliography,
    DataStrategy,
    DesignLimitation,
    IndependentVerificationReport,
    MethodologyBlueprint,
    Preregistration,
    ResearchMethod,
    ResearchParadigm,
    ResearchReport,
    RQBrief,
    SourceVerificationReport,
    SynthesisReport,
    ValidityCriterion,
)
from academic_pipeline.models.review import EditorReview
from academic_pipeline.research.agents import agents as _agents
from academic_pipeline.research.graph import (
    BibliographyNode,
    ChainOfIdeasNode,
    CrossModelVerificationNode,
    EditorInChiefNode,
    MergeReviewsNode,
    ReportCompilerNode,
    ResearchArchitectNode,
    ResearchQuestionNode,
    SourceVerificationNode,
    SynthesisNode,
    build_research_graph,
)
from academic_pipeline.research.state import ResearchState
from tests.conftest import make_test_deps
from tests.unit.core.test_serialization import _make_rq_brief


def _make_methodology_blueprint() -> MethodologyBlueprint:
    """Create a minimal MethodologyBlueprint for testing."""
    return MethodologyBlueprint(
        paradigm=ResearchParadigm(selected="Pragmatist", justification="Fits RQ"),
        method=ResearchMethod(type="quantitative", specific_method="survey", justification="Best fit"),
        data_strategy=DataStrategy(data_type="Primary", sources="Survey", sampling="Random", time_frame="2024"),
        analytical_framework=AnalyticalFramework(technique="Regression", steps="Collect, Analyze", tools="SPSS"),
        validity_criteria=[ValidityCriterion(criterion="Internal validity", strategy="Control group")],
        limitations=[DesignLimitation(limitation="Small sample", mitigation="Acknowledge in discussion")],
        ethical_considerations=["Informed consent"],
        reporting_standard="STROBE",
        preregistration=Preregistration(recommended=True, platform="OSF", status="Planned"),
    )


pytestmark = pytest.mark.anyio

# PromptedOutput agents need TestModel with custom_output_text containing valid
# JSON (not tool calls).  Map each agent name to its output model class so we
# can auto-generate valid JSON from the schema.
_StructuredModel = (
    RQBrief
    | MethodologyBlueprint
    | Bibliography
    | SourceVerificationReport
    | SynthesisReport
    | ResearchReport
    | EditorReview
    | EthicsChecklist
    | IndependentVerificationReport
    | DevelopmentChain
    | ThesisStatement
)

_STRUCTURED_AGENT_MODELS: dict[str, type[_StructuredModel]] = {
    "research_question": RQBrief,
    "research_architect": MethodologyBlueprint,
    "bibliography": Bibliography,
    "source_verification": SourceVerificationReport,
    # PRD §6.1.T7 — knowledge_graph agent + KnowledgeGraph model deleted.
    "synthesis": SynthesisReport,
    "report_compiler": ResearchReport,
    "independent_verifier": IndependentVerificationReport,
    "editor_in_chief": EditorReview,
    # PRD §6.1.T6 — ethics_review agent moved to integrity.agents.
    # PRD §6.1.T1 — CoI extractor + thesis extractor are now invoked by default
    # (chain_of_ideas_enabled defaults to true in Phase 4), so the override
    # fixture must supply valid structured JSON for both.
    "chain_of_ideas_extractor": DevelopmentChain,
    "thesis_extractor": ThesisStatement,
}

_STRUCTURED_AGENTS = set(_STRUCTURED_AGENT_MODELS)

_ALL_NODES = [
    ResearchQuestionNode,
    ResearchArchitectNode,
    BibliographyNode,
    SourceVerificationNode,
    SynthesisNode,
    ChainOfIdeasNode,
    ReportCompilerNode,
    CrossModelVerificationNode,
    EditorInChiefNode,
    MergeReviewsNode,
]


def _json_for_model(model_cls: type[_StructuredModel], seed: int = 0) -> str:
    """Generate valid JSON text from a Pydantic model's schema for TestModel.

    Prefers a hand-built fixture (when registered in
    ``tests.conftest.FIXTURE_INSTANCES``) so models with output_validators —
    e.g., :class:`EthicsChecklist` — get a checklist that passes validation.
    """
    from tests.conftest import FIXTURE_INSTANCES, _init_fixture_instances

    _init_fixture_instances()
    if model_cls in FIXTURE_INSTANCES:
        return FIXTURE_INSTANCES[model_cls].model_dump_json()
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, seed).generate()
    return pydantic_core.to_json(data).decode()


def _override_all(output: str = "Verdict: PASS\n\nAll good.") -> contextlib.ExitStack:
    """Create an ExitStack that overrides every agent with a TestModel.

    Structured-output agents use PromptedOutput, so TestModel needs custom_output_text with valid JSON. String-output
    agents use custom_output_text with plain text.
    """
    text_model = TestModel(custom_output_text=output, call_tools=[])
    stack = contextlib.ExitStack()
    for name, agent in _agents.items():
        if name in _STRUCTURED_AGENT_MODELS:
            model_cls = _STRUCTURED_AGENT_MODELS[name]
            json_text = _json_for_model(model_cls)
            struct_model = TestModel(custom_output_text=json_text, call_tools=[])
            stack.enter_context(agent.override(model=struct_model))
        else:
            stack.enter_context(agent.override(model=text_model))
    return stack


class TestMergeReviewsRouting:
    """MergeReviews: always terminal — End on all paths."""

    async def test_blocked_ends(self) -> None:
        state = ResearchState(
            topic="AI in education",
            eic_review="Good review.",
            ethics_verdict=Verdict.BLOCKED,
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all("Verdict: PASS\n\nAll good."):
            graph = Graph(nodes=_ALL_NODES)
            result = await graph.run(MergeReviewsNode(), state=state, deps=deps)

        assert result.output is not None

    async def test_no_revision_ends(self) -> None:
        state = ResearchState(
            topic="AI in education",
            eic_review="All good.",
            needs_revision=False,
            review_report={"content": "Final report."},
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all():
            graph = Graph(nodes=_ALL_NODES)
            result = await graph.run(MergeReviewsNode(), state=state, deps=deps)

        assert result.output is not None

    async def test_needs_revision_still_ends(self) -> None:
        """Even with needs_revision=True, MergeReviews is now terminal."""
        state = ResearchState(
            topic="AI in education",
            eic_review="Needs major revision.",
            needs_revision=True,
            review_report={"content": "Draft report."},
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all():
            graph = Graph(nodes=_ALL_NODES)
            result = await graph.run(MergeReviewsNode(), state=state, deps=deps)

        # Terminal — no backward routing
        assert result.output is not None


class TestLinearNodes:
    """Test that linear nodes update state correctly."""

    async def test_research_question_node_updates_rq_brief(self) -> None:
        state = ResearchState(topic="AI in education")
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all():
            graph = Graph(nodes=_ALL_NODES)
            await graph.run(ResearchQuestionNode(), state=state, deps=deps)

        assert state.rq_brief is not None
        assert state.rq_brief.research_question
        assert state.rq_brief.finer_scores is not None
        assert state.rq_brief.sub_questions is not None
        assert len(state.messages) >= 1

    async def test_research_architect_node_updates_blueprint(self) -> None:
        state = ResearchState(
            topic="AI in education",
            rq_brief=_make_rq_brief(),
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all("Methodology blueprint output."):
            graph = Graph(nodes=_ALL_NODES)
            await graph.run(ResearchArchitectNode(), state=state, deps=deps)

        assert state.methodology_blueprint is not None
        assert state.methodology_blueprint.paradigm is not None
        assert len(state.messages) >= 1


class TestEditorInChiefStructuredOutput:
    """EditorInChiefNode should use structured EditorReview output."""

    async def test_eic_sets_structured_review(self) -> None:
        state = ResearchState(
            topic="AI in education",
            review_report={"content": "A full research report."},
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all("Verdict: PASS\n\nAll good."):
            # Start from EIC node, runs through Ethics and MergeReviews
            graph = Graph(nodes=_ALL_NODES)
            result = await graph.run(EditorInChiefNode(), state=state, deps=deps)

        # Structured review should be set
        assert state.eic_review_structured is not None
        assert state.eic_review != ""
        assert result.output is not None

    async def test_eic_accept_does_not_need_revision(self) -> None:
        """TestModel generates EditorReview with verdict=Accept by default."""
        state = ResearchState(
            topic="AI in education",
            review_report={"content": "Excellent research report."},
        )
        deps = make_test_deps()
        deps.config = deps.config.model_copy(update={"enable_node_evaluation": False})

        with _override_all():
            graph = Graph(nodes=_ALL_NODES)
            await graph.run(EditorInChiefNode(), state=state, deps=deps)

        # Default TestModel produces Accept verdict
        assert state.eic_review_structured is not None
        assert state.needs_revision is False


# PRD §6.1.T7 — TestKnowledgeGraphNode and its 4 tests deleted; the
# KnowledgeGraphNode class + KnowledgeGraph model were removed. See
# `tests/unit/research/test_chain_of_ideas.py::test_knowledge_graph_*`
# for the deletion contract tests.


class TestNewLinearGraph:
    """The research graph is now a straight line — no DA checkpoints."""

    async def test_graph_has_no_da_checkpoint_nodes(self) -> None:
        graph = build_research_graph()
        assert "DACheckpoint1Node" not in graph.node_defs
        assert "DACheckpoint2Node" not in graph.node_defs

    async def test_graph_has_10_nodes(self) -> None:
        # PRD §6.1.T7 removed KnowledgeGraphNode (11 → 10).
        # PRD §6.1.T6 removed EthicsReviewNode (12 → 11).
        # Spec 2 Phase 1 added ChainOfIdeasNode between Synthesis + ReportCompiler.
        graph = build_research_graph()
        assert len(graph.node_defs) == 10
