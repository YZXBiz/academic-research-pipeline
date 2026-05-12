"""Unit tests for PydanticAI pipeline orchestrator nodes."""

from __future__ import annotations

import contextlib

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_graph import End, GraphRunContext

from academic_pipeline.core.enums import PipelineStatus, Stage
from academic_pipeline.integrity.agents import agents as _integrity_agents
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
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
    EditorialSynthesis,
    EditorReview,
    EICReview,
    FieldAnalysis,
    PeerReviewOutput,
    PeerReviewReport,
)
from academic_pipeline.models.shared import (
    Author,
    Reference,
)
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
from academic_pipeline.pipeline.nodes import (
    AbortNode,
    ExperimentPhaseNode,
    FinalIntegrityFixNode,
    FinalIntegrityNode,
    FinalizeNode,
    IntakeNode,
    IntegrityFixNode,
    NoveltyGateNode,
    PreIntegrityNode,
    ReviewPhaseNode,
    SummaryNode,
)
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.research.agents import agents as research_agents
from academic_pipeline.review.agents import agents as review_agents
from academic_pipeline.writing.agents import agents as writing_agents
from tests.conftest import make_structured_test_model, make_structured_test_model_with_overrides, make_test_deps


def _make_test_paper_draft() -> PaperDraft:
    """Create a minimal valid PaperDraft for test fixtures."""
    return PaperDraft(
        title="Test",
        abstract="A test paper about machine learning.",
        authors=[Author(name="Test Author", affiliation="Test University")],
        keywords=["machine", "learning", "test"],
        sections=[
            Section(
                heading="Introduction",
                level=1,
                content="Some paper content here.",
                word_count=50,
                citation_count=0,
            ),
        ],
        references=[Reference(id="r1", full_citation="Test (2024). A test paper.")],
        total_word_count=50,
    )


def _unique_run_id() -> str:
    """Generate a unique run_id to avoid stale persistence collisions."""
    import uuid

    return f"test-{uuid.uuid4().hex[:8]}"


pytestmark = pytest.mark.anyio


# Model class mapping for each structured agent.
_RESEARCH_MODEL_MAP: dict[str, type] = {
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

_WRITING_MODEL_MAP: dict[str, type] = {
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
}

_REVIEW_MODEL_MAP: dict[str, type] = {
    "field_analyst": FieldAnalysis,
    "eic": EICReview,
    "methodology_reviewer": PeerReviewReport,
    "domain_reviewer": PeerReviewReport,
    "perspective_reviewer": PeerReviewReport,
    "editorial_synthesizer": EditorialSynthesis,
}


def _override_all_subgraph_agents(
    output: str = "Verdict: PASS\n\nAll good.",
    *,
    integrity_verdict: str = "PASS",
    review_decision: str = "Accept",
) -> contextlib.ExitStack:
    """Override every agent across all subgraph modules with a TestModel.

    Args:
        output: Text output for non-structured agents.
        integrity_verdict: Verdict for the integrity agent (PASS/FAIL).
        review_decision: Decision for the editorial_synthesizer (Accept/Reject/Major Revision/Minor Revision).
    """
    text_model = TestModel(custom_output_text=output, call_tools=[])
    integrity_model = make_structured_test_model_with_overrides(
        IntegrityVerificationOutput,
        {"verdict": integrity_verdict, "summary": output, "report": output},
    )
    editorial_model = make_structured_test_model_with_overrides(
        EditorialSynthesis,
        {"decision": review_decision, "summary": output, "report": output},
    )
    stack = contextlib.ExitStack()

    for name, agent in research_agents.items():
        if name in _RESEARCH_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_RESEARCH_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=text_model))

    for name, agent in writing_agents.items():
        if name in _WRITING_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_WRITING_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=text_model))

    for name, agent in review_agents.items():
        if name == "editorial_synthesizer":
            stack.enter_context(agent.override(model=editorial_model))
        elif name in _REVIEW_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_REVIEW_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=text_model))

    stack.enter_context(_integrity_agents["integrity_verification"].override(model=integrity_model))
    stack.enter_context(
        _integrity_agents["compliance_check"].override(model=make_structured_test_model(ComplianceReport))
    )
    return stack


class TestIntakeNode:
    """IntakeNode sets current_stage and pipeline_status."""

    async def test_intake_sets_stage_and_status(self) -> None:
        state = PipelineState(topic="AI in education")
        deps = make_test_deps()

        with _override_all_subgraph_agents():
            node = IntakeNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert state.current_stage == Stage.RESEARCH
        assert state.pipeline_status == PipelineStatus.RUNNING
        assert isinstance(result, NoveltyGateNode)

    async def test_intake_preserves_existing_run_id(self) -> None:
        state = PipelineState(topic="AI in education", run_id="test-123")
        deps = make_test_deps()

        with _override_all_subgraph_agents():
            node = IntakeNode()
            await node.run(GraphRunContext(state=state, deps=deps))

        assert state.run_id == "test-123"

    async def test_intake_generates_run_id_when_empty(self) -> None:
        state = PipelineState(topic="AI in education")
        deps = make_test_deps()

        with _override_all_subgraph_agents():
            node = IntakeNode()
            await node.run(GraphRunContext(state=state, deps=deps))

        assert state.run_id != ""
        assert len(state.run_id) == 8


class TestIntegrityRouting:
    """PreIntegrityNode routes to ReviewPhaseNode on PASS, IntegrityFixNode on FAIL."""

    async def test_pass_routes_to_review(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents("Verdict: PASS\n\nAll clear."):
            node = PreIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, ReviewPhaseNode)

    async def test_fail_routes_to_fix(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(integrity_verdict="FAIL"):
            node = PreIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, IntegrityFixNode)

    async def test_max_fixes_forces_review(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
            integrity_fix_count=3,  # At max (default max_integrity_fix_loops=3)
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(integrity_verdict="FAIL"):
            node = PreIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        # At max fix count, should force proceed to review
        assert isinstance(result, ReviewPhaseNode)

    async def test_pass_with_conditions_routes_to_review(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(integrity_verdict="PASS WITH NOTES"):
            node = PreIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, ReviewPhaseNode)


class TestReviewRouting:
    """ReviewPhaseNode is read-only — always routes to FinalIntegrityNode."""

    async def test_accept_routes_to_final_integrity(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(review_decision="Accept"):
            node = ReviewPhaseNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityNode)

    async def test_reject_still_routes_to_final_integrity(self) -> None:
        """Review is read-only — even Reject proceeds to final integrity."""
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(review_decision="Reject"):
            node = ReviewPhaseNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityNode)

    async def test_major_revision_still_routes_to_final_integrity(self) -> None:
        """Review is read-only — Major Revision proceeds to final integrity."""
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(review_decision="Major Revision"):
            node = ReviewPhaseNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityNode)

    async def test_review_merges_outputs_and_sets_stage(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(review_decision="Accept"):
            node = ReviewPhaseNode()
            await node.run(GraphRunContext(state=state, deps=deps))

        assert state.current_stage == Stage.FINAL_INTEGRITY
        assert any("Review phase complete" in m["content"] for m in state.messages)


class TestFinalIntegrityRouting:
    """FinalIntegrityNode routes based on verdict, including max fix loop check."""

    async def test_fail_routes_to_final_integrity_fix(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
            integrity_fix_count=0,
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(integrity_verdict="FAIL"):
            node = FinalIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityFixNode)

    async def test_fail_max_loops_forces_finalize(self) -> None:
        state = PipelineState(
            topic="test",
            run_id=_unique_run_id(),
            paper_draft=_make_test_paper_draft(),
            integrity_fix_count=3,  # At max (default max_integrity_fix_loops=3)
        )
        deps = make_test_deps()

        with _override_all_subgraph_agents(integrity_verdict="FAIL"):
            node = FinalIntegrityNode()
            result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalizeNode)


class TestFinalIntegrityFixNode:
    """FinalIntegrityFixNode increments fix count and returns FinalIntegrityNode."""

    async def test_increments_fix_count_and_returns_final_integrity(self) -> None:
        state = PipelineState(
            topic="test",
            paper_draft=_make_test_paper_draft(),
            integrity_fix_count=0,
            integrity_report={"issues": ["citation missing", "plagiarism detected"]},
        )
        deps = make_test_deps()

        node = FinalIntegrityFixNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityNode)
        assert state.integrity_fix_count == 1
        assert any("Final integrity fix round 1" in m["content"] for m in state.messages)

    async def test_second_fix_round(self) -> None:
        state = PipelineState(
            topic="test",
            paper_draft=_make_test_paper_draft(),
            integrity_fix_count=1,
            integrity_report={"reason": "Still has issues"},
        )
        deps = make_test_deps()

        node = FinalIntegrityFixNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, FinalIntegrityNode)
        assert state.integrity_fix_count == 2


class TestSummaryNode:
    """SummaryNode sets completed status and returns End."""

    async def test_summary_completes_pipeline(self) -> None:
        state = PipelineState(
            topic="test",
            pipeline_status=PipelineStatus.RUNNING,
        )
        deps = make_test_deps()

        node = SummaryNode()
        await node.run(GraphRunContext(state=state, deps=deps))

        assert state.pipeline_status == PipelineStatus.COMPLETED
        assert state.current_stage == Stage.SUMMARY


class TestAbortNode:
    """AbortNode sets aborted status and returns End."""

    async def test_abort_sets_status(self) -> None:
        state = PipelineState(
            topic="test",
            pipeline_status=PipelineStatus.RUNNING,
        )
        deps = make_test_deps()

        node = AbortNode()
        await node.run(GraphRunContext(state=state, deps=deps))

        assert state.pipeline_status == PipelineStatus.ABORTED

    async def test_abort_returns_end(self) -> None:
        state = PipelineState(
            topic="test",
            pipeline_status=PipelineStatus.RUNNING,
        )
        deps = make_test_deps()

        node = AbortNode()
        result = await node.run(GraphRunContext(state=state, deps=deps))

        assert isinstance(result, End)
        assert result.data == "Pipeline aborted."
        assert any("Pipeline aborted" in m["content"] for m in state.messages)


class TestSummarizeIntegrityIssues:
    """Summarize_integrity_issues extracts short summaries from integrity report dicts."""

    def _make_state(self, report: dict[str, object]) -> PipelineState:
        return PipelineState(topic="test", integrity_report=report)  # type: ignore[arg-type]

    def test_issues_list(self) -> None:
        state = self._make_state({"issues": ["missing ref", "bad citation", "typo"]})
        result = state.summarize_integrity_issues()
        assert "missing ref" in result
        assert "bad citation" in result
        assert "typo" in result

    def test_issues_list_truncates_at_five(self) -> None:
        state = self._make_state({"issues": [f"issue {i}" for i in range(10)]})
        result = state.summarize_integrity_issues()
        assert "issue 0" in result
        assert "issue 4" in result
        assert "issue 5" not in result

    def test_reason_fallback(self) -> None:
        state = self._make_state({"reason": "Citation formatting error"})
        assert state.summarize_integrity_issues() == "Citation formatting error"

    def test_raw_fallback(self) -> None:
        state = self._make_state({"raw": "Some raw integrity output"})
        assert state.summarize_integrity_issues() == "Some raw integrity output"

    def test_empty_report_fallback(self) -> None:
        state = self._make_state({})
        result = state.summarize_integrity_issues()
        assert isinstance(result, str)
        assert len(result) <= 200

    def test_empty_issues_list_falls_through(self) -> None:
        state = self._make_state({"issues": [], "reason": "Fallback reason"})
        assert state.summarize_integrity_issues() == "Fallback reason"


class TestStageReinforcement:
    def test_reinforcement_injected_for_known_stage(self) -> None:
        state = PipelineState(topic="AI in education")
        state.inject_reinforcement(Stage.PRE_INTEGRITY)
        assert any("[REINFORCEMENT]" in m["content"] for m in state.messages)
        assert any("MANDATORY" in m["content"] for m in state.messages)

    def test_no_reinforcement_for_research_stage(self) -> None:
        state = PipelineState(topic="AI in education")
        state.inject_reinforcement(Stage.RESEARCH)
        assert not any("[REINFORCEMENT]" in m.get("content", "") for m in state.messages)

    def test_reinforcement_dict_has_three_stages(self) -> None:
        assert Stage.PRE_INTEGRITY in PipelineState.STAGE_REINFORCEMENTS
        assert Stage.REVIEW in PipelineState.STAGE_REINFORCEMENTS
        assert Stage.FINAL_INTEGRITY in PipelineState.STAGE_REINFORCEMENTS
        assert len(PipelineState.STAGE_REINFORCEMENTS) == 3


class TestExperimentPhaseNodeAbortBehavior:
    """ExperimentPhaseNode must distinguish interruption from genuine failure.

    Regression: previously ANY return from the experiment subgraph with
    final_state.results=None routed to AbortNode, which sets
    pipeline_status=ABORTED and writes the terminal End snapshot. After that,
    pydantic_graph load_next() returns None on resume → "Unable to restore
    snapshot from state persistence" → run is permanently dead.

    The fix: empty results + empty error_history → raise (recorded as 'error'
    snapshot, resumable). Only empty results WITH errors → AbortNode.
    """

    @pytest.mark.anyio()
    async def test_interrupted_run_raises_for_resumability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subgraph returns empty results AND empty error_history → raise.

        This simulates SIGTERM/SSE-drop interruption: the subgraph cleanup
        reaches End with no results populated and no agent has explicitly
        recorded a failure. The orchestrator must NOT seal the run via
        AbortNode — it must raise so the snapshot system records the node
        as 'error' (which `_reset_crashed_snapshots` will later flip to
        'created' on resume).
        """
        from dataclasses import dataclass

        @dataclass
        class _FakeFinalState:
            results: object = None
            analysis: object = None
            plan: object = None
            generated_code: str = ""
            error_history: list[str] = None  # type: ignore[assignment]

            def __post_init__(self) -> None:
                if self.error_history is None:
                    self.error_history = []

        async def _fake_run_subgraph(*args: object, **kwargs: object) -> object:
            return _FakeFinalState()

        monkeypatch.setattr(
            "academic_pipeline.pipeline.nodes._run_subgraph_with_persistence",
            _fake_run_subgraph,
        )

        state = PipelineState(topic="test", run_id="test-interrupt")
        deps = make_test_deps()
        ctx = GraphRunContext(state=state, deps=deps)

        with pytest.raises(RuntimeError, match="interrupted by signal or network drop"):
            await ExperimentPhaseNode().run(ctx)

        # State must be marked so resume can detect the situation
        assert any(
            "interruption" in m.get("content", "").lower() for m in state.messages
        ), "State should record an interruption message for the user"

    @pytest.mark.anyio()
    async def test_genuine_failure_still_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subgraph returns empty results WITH error_history → AbortNode.

        Real failures (ml_engineer gave up after retries, dataset URLs all
        broken, etc.) should still seal the run via AbortNode. Only the
        no-explicit-failure case is treated as interruption.
        """
        from dataclasses import dataclass

        @dataclass
        class _FakeFinalState:
            results: object = None
            analysis: object = None
            plan: object = None
            generated_code: str = ""
            error_history: list[str] = None  # type: ignore[assignment]

            def __post_init__(self) -> None:
                if self.error_history is None:
                    self.error_history = ["ml_engineer gave up: dataset URL 404"]

        async def _fake_run_subgraph(*args: object, **kwargs: object) -> object:
            return _FakeFinalState()

        monkeypatch.setattr(
            "academic_pipeline.pipeline.nodes._run_subgraph_with_persistence",
            _fake_run_subgraph,
        )

        state = PipelineState(topic="test", run_id="test-realfail")
        deps = make_test_deps()
        ctx = GraphRunContext(state=state, deps=deps)

        result = await ExperimentPhaseNode().run(ctx)
        assert isinstance(result, AbortNode), "Genuine failure (error_history populated) must still route to AbortNode"
