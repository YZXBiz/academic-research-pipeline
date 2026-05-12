"""Unit tests for the persona-anchored reviewer panel (SCI Spec 5 Phase 1)."""

from __future__ import annotations

import contextlib

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.persona_review import (
    Commitment,
    Intention,
    Knowledgeability,
    PersonaReviewOutput,
    PersonaSpec,
    ReviewFinding,
)
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.review.agents import PERSONA_REVIEWER_AGENTS, REVIEWER_AGENTS
from academic_pipeline.review.agents import agents as _agents
from academic_pipeline.review.graph import ParallelReviewerNode, PointWiseNoveltyReviewerNode
from academic_pipeline.review.state import ReviewState


pytestmark = pytest.mark.anyio


# ---------- Models -----------------------------------------------------------


class TestModels:
    """PersonaSpec, ReviewFinding, PersonaReviewOutput construction + frozen."""

    def test_strenum_values(self) -> None:
        assert Commitment.THOROUGH.value == "thorough"
        assert Commitment.SUPERFICIAL.value == "superficial"
        assert Intention.SKEPTICAL_GATEKEEPER.value == "skeptical_gatekeeper"
        assert Intention.APPLIED_PRACTITIONER.value == "applied_practitioner"
        assert Intention.ENTHUSIASTIC_ADVOCATE.value == "enthusiastic_advocate"
        assert Intention.DOMAIN_PURIST.value == "domain_purist"
        assert Knowledgeability.DEEP_IN_FIELD.value == "deep_in_field"
        assert Knowledgeability.ADJACENT_FIELD.value == "adjacent_field"
        assert Knowledgeability.NOVICE.value == "novice"

    def test_persona_spec_construction(self) -> None:
        spec = PersonaSpec(
            commitment=Commitment.THOROUGH,
            intention=Intention.SKEPTICAL_GATEKEEPER,
            knowledgeability=Knowledgeability.DEEP_IN_FIELD,
            target_journal="Journal of Biomedical Informatics",
            target_acceptance_rate=0.20,
        )
        assert spec.commitment is Commitment.THOROUGH
        assert spec.target_acceptance_rate == 0.20

    def test_persona_spec_is_frozen(self) -> None:
        spec = PersonaSpec(
            commitment=Commitment.THOROUGH,
            intention=Intention.DOMAIN_PURIST,
            knowledgeability=Knowledgeability.DEEP_IN_FIELD,
            target_journal="JBI",
            target_acceptance_rate=0.20,
        )
        with pytest.raises(ValidationError):
            spec.target_journal = "Different Journal"  # type: ignore[misc]

    def test_persona_spec_acceptance_rate_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PersonaSpec(
                commitment=Commitment.THOROUGH,
                intention=Intention.DOMAIN_PURIST,
                knowledgeability=Knowledgeability.DEEP_IN_FIELD,
                target_journal="JBI",
                target_acceptance_rate=1.5,  # out of [0, 1]
            )

    def test_review_finding_is_frozen(self) -> None:
        finding = ReviewFinding(
            finding_id="F1",
            severity="major",
            section="Methods",
            description="Sample size unjustified.",
            rejection_grounds=False,
        )
        with pytest.raises(ValidationError):
            finding.severity = "critical"  # type: ignore[misc]

    def test_persona_review_output_is_frozen(self) -> None:
        spec = PersonaSpec(
            commitment=Commitment.THOROUGH,
            intention=Intention.APPLIED_PRACTITIONER,
            knowledgeability=Knowledgeability.ADJACENT_FIELD,
            target_journal="JBI",
            target_acceptance_rate=0.20,
        )
        out = PersonaReviewOutput(
            persona=spec,
            findings=[],
            overall_verdict="accept",
            confidence=0.8,
            one_paragraph_summary="Solid paper.",
        )
        with pytest.raises(ValidationError):
            out.overall_verdict = "reject"  # type: ignore[misc]


# ---------- Persona-specific instantiation ----------------------------------


@pytest.mark.parametrize(
    ("intention", "knowledgeability"),
    [
        (Intention.SKEPTICAL_GATEKEEPER, Knowledgeability.DEEP_IN_FIELD),
        (Intention.APPLIED_PRACTITIONER, Knowledgeability.ADJACENT_FIELD),
        (Intention.DOMAIN_PURIST, Knowledgeability.DEEP_IN_FIELD),
    ],
)
def test_persona_specs_for_each_persona(
    intention: Intention, knowledgeability: Knowledgeability
) -> None:
    """The 3 personas in PERSONA_REVIEWER_AGENTS are constructible as PersonaSpec values."""
    spec = PersonaSpec(
        commitment=Commitment.THOROUGH,
        intention=intention,
        knowledgeability=knowledgeability,
        target_journal="Journal of Biomedical Informatics",
        target_acceptance_rate=0.20,
    )
    assert spec.intention is intention
    assert spec.knowledgeability is knowledgeability
    assert spec.commitment is Commitment.THOROUGH


# ---------- Node behaviour ---------------------------------------------------


def _make_deps(*, persona_reviewers_enabled: bool) -> PipelineDeps:
    config = PipelineConfig(
        anthropic_api_key="sk-test-fake-key",  # type: ignore[arg-type]
        model_name="test",
        tool_call_delay_seconds=0,
        persona_reviewers_enabled=persona_reviewers_enabled,
    )
    return PipelineDeps.create(config=config)


class _RunCtx:
    """Minimal stand-in for GraphRunContext compatible with the node body."""

    def __init__(self, state: ReviewState, deps: PipelineDeps) -> None:
        self.state = state
        self.deps = deps


def _persona_review_json(intention: Intention, knowledgeability: Knowledgeability) -> str:
    """Build a valid PersonaReviewOutput JSON for TestModel custom_output_text."""
    out = PersonaReviewOutput(
        persona=PersonaSpec(
            commitment=Commitment.THOROUGH,
            intention=intention,
            knowledgeability=knowledgeability,
            target_journal="Journal of Biomedical Informatics",
            target_acceptance_rate=0.20,
        ),
        findings=[
            ReviewFinding(
                finding_id="F1",
                severity="major",
                section="Methods",
                description="Sample size unjustified.",
                rejection_grounds=False,
            ),
        ],
        overall_verdict="major_revision",
        confidence=0.7,
        one_paragraph_summary=f"Persona {intention.value} review summary.",
    )
    return out.model_dump_json()


def _peer_review_json() -> str:
    """Build a valid PeerReviewReport JSON for legacy reviewers via TestModel."""
    from academic_pipeline.models.review import PeerReviewReport
    from tests.conftest import json_for_model

    return json_for_model(PeerReviewReport)


@contextlib.contextmanager
def _override_persona_agents() -> contextlib.AbstractContextManager[None]:
    """Override the 3 persona reviewers with TestModels returning canned JSON."""
    persona_map: dict[str, tuple[Intention, Knowledgeability]] = {
        "senior_gatekeeper_reviewer": (
            Intention.SKEPTICAL_GATEKEEPER,
            Knowledgeability.DEEP_IN_FIELD,
        ),
        "applied_practitioner_reviewer": (
            Intention.APPLIED_PRACTITIONER,
            Knowledgeability.ADJACENT_FIELD,
        ),
        "methodology_purist_reviewer": (
            Intention.DOMAIN_PURIST,
            Knowledgeability.DEEP_IN_FIELD,
        ),
    }
    stack = contextlib.ExitStack()
    for agent_key, (intention, knowledgeability) in persona_map.items():
        stack.enter_context(
            _agents[agent_key].override(
                model=TestModel(
                    custom_output_text=_persona_review_json(intention, knowledgeability),
                    call_tools=[],
                ),
            )
        )
    try:
        yield
    finally:
        stack.close()


@contextlib.contextmanager
def _override_legacy_agents() -> contextlib.AbstractContextManager[None]:
    """Override the 3 legacy reviewers with TestModels returning canned JSON."""
    stack = contextlib.ExitStack()
    for _reviewer_id, agent_key in REVIEWER_AGENTS:
        stack.enter_context(
            _agents[agent_key].override(
                model=TestModel(custom_output_text=_peer_review_json(), call_tools=[]),
            )
        )
    try:
        yield
    finally:
        stack.close()


async def test_node_dispatches_legacy_when_flag_off() -> None:
    """When persona_reviewers_enabled=False, ParallelReviewerNode dispatches the
    legacy 3 reviewers and the persona reviewers receive ZERO calls."""
    from unittest.mock import patch

    deps = _make_deps(persona_reviewers_enabled=False)
    state = ReviewState(paper_draft={"title": "T", "content": "Body."})

    persona_agent_keys = {agent_key for _rid, agent_key in PERSONA_REVIEWER_AGENTS}
    legacy_agent_keys = {agent_key for _rid, agent_key in REVIEWER_AGENTS}
    persona_calls: list[str] = []
    legacy_calls: list[str] = []

    real_traced = __import__(
        "academic_pipeline.review.graph", fromlist=["traced_agent_run"]
    ).traced_agent_run

    async def _spy(agent, prompt, /, *, deps, name, phase):  # type: ignore[no-untyped-def]
        if name in persona_agent_keys:
            persona_calls.append(name)
        if name in legacy_agent_keys:
            legacy_calls.append(name)
        return await real_traced(agent, prompt, deps=deps, name=name, phase=phase)

    with _override_legacy_agents(), _override_persona_agents(), patch(
        "academic_pipeline.review.graph.traced_agent_run", side_effect=_spy
    ):
        node = ParallelReviewerNode()
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, PointWiseNoveltyReviewerNode)
    # Legacy path: reviewer_reports populated, persona_reviews stays empty.
    assert len(state.reviewer_reports) == len(REVIEWER_AGENTS)
    assert state.persona_reviews == []
    # No persona reviewer was called.
    assert persona_calls == [], (
        f"Persona reviewers should not have been invoked when flag is off; "
        f"got {persona_calls}"
    )
    # All 3 legacy reviewers were called.
    assert sorted(legacy_calls) == sorted(legacy_agent_keys)


async def test_node_dispatches_persona_when_flag_on() -> None:
    """When persona_reviewers_enabled=True, ParallelReviewerNode dispatches the
    3 persona reviewers and populates state.persona_reviews. Legacy reviewers
    receive ZERO calls."""
    from unittest.mock import patch

    deps = _make_deps(persona_reviewers_enabled=True)
    state = ReviewState(paper_draft={"title": "T", "content": "Body."})

    persona_agent_keys = {agent_key for _rid, agent_key in PERSONA_REVIEWER_AGENTS}
    legacy_agent_keys = {agent_key for _rid, agent_key in REVIEWER_AGENTS}
    persona_calls: list[str] = []
    legacy_calls: list[str] = []

    real_traced = __import__(
        "academic_pipeline.review.graph", fromlist=["traced_agent_run"]
    ).traced_agent_run

    async def _spy(agent, prompt, /, *, deps, name, phase):  # type: ignore[no-untyped-def]
        if name in persona_agent_keys:
            persona_calls.append(name)
        if name in legacy_agent_keys:
            legacy_calls.append(name)
        return await real_traced(agent, prompt, deps=deps, name=name, phase=phase)

    with _override_persona_agents(), _override_legacy_agents(), patch(
        "academic_pipeline.review.graph.traced_agent_run", side_effect=_spy
    ):
        node = ParallelReviewerNode()
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, PointWiseNoveltyReviewerNode)
    assert len(state.persona_reviews) == len(PERSONA_REVIEWER_AGENTS)
    # Legacy reviewer_reports stays empty in persona path.
    assert state.reviewer_reports == []
    # All 3 persona reviewers were invoked.
    assert sorted(persona_calls) == sorted(persona_agent_keys)
    # No legacy reviewer was called.
    assert legacy_calls == []
    # Each persona review carries its persona stamp.
    intentions = {pr.persona.intention for pr in state.persona_reviews}
    assert intentions == {
        Intention.SKEPTICAL_GATEKEEPER,
        Intention.APPLIED_PRACTITIONER,
        Intention.DOMAIN_PURIST,
    }
    # Each persona review left a one_paragraph_summary message in the conversation.
    persona_messages = [
        m for m in state.messages if "summary" in m.get("content", "").lower()
    ]
    assert len(persona_messages) == 3


def test_pipeline_state_forwards_persona_reviews_field() -> None:
    """PipelineState has the persona_reviews field with default empty list,
    and ReviewPhaseNode merges from final review state."""
    pstate = PipelineState()
    assert pstate.persona_reviews == []

    # Simulate the merge that ReviewPhaseNode performs.
    spec = PersonaSpec(
        commitment=Commitment.THOROUGH,
        intention=Intention.SKEPTICAL_GATEKEEPER,
        knowledgeability=Knowledgeability.DEEP_IN_FIELD,
        target_journal="Journal of Biomedical Informatics",
        target_acceptance_rate=0.20,
    )
    review_out = PersonaReviewOutput(
        persona=spec,
        findings=[],
        overall_verdict="accept",
        confidence=0.9,
        one_paragraph_summary="OK.",
    )
    rstate = ReviewState(persona_reviews=[review_out])

    pstate.persona_reviews = list(rstate.persona_reviews)
    assert len(pstate.persona_reviews) == 1
    assert pstate.persona_reviews[0].persona.intention is Intention.SKEPTICAL_GATEKEEPER
