"""Unit tests for the cascaded reviewer pipeline (SCI Spec 6 Phase 1).

Covers:
- Models construction + frozen
- aggregate_cascade_result over short-circuit / pass / not-run combinations
- Stage A regex fallback when traceability off
- Stage B reads novelty_report correctly
- Stage C reads persona_reviews correctly
- Stage D always passes
- CascadedReviewNode: flag off → not invoked
- CascadedReviewNode: flag on, all-pass → cascade_result populated, accept
- CascadedReviewNode: flag on, novelty rejects → short-circuits at B
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.cascade import (
    CascadeResult,
    CascadeStageName,
    ClaimAuditFinding,
    ClaimAuditReport,
    StageResult,
    StageVerdict,
)
from academic_pipeline.models.novelty_report import (
    ClaimAssessment,
    ClaimNoveltyDimension,
    ClaimVerdict,
    ContributionClaim,
    NoveltyReport,
)
from academic_pipeline.models.persona_review import (
    Commitment,
    Intention,
    Knowledgeability,
    PersonaReviewOutput,
    PersonaSpec,
    ReviewFinding,
)
from academic_pipeline.review.cascade_aggregation import aggregate_cascade_result
from academic_pipeline.review.cascade_stages import (
    run_methodology_stage,
    run_narrative_stage,
    run_novelty_stage,
    run_numerical_grounding_stage,
)
from academic_pipeline.review.graph import (
    CascadedReviewNode,
    EditorialSynthesizerNode,
    PointWiseNoveltyReviewerNode,
)
from academic_pipeline.review.state import ReviewState


pytestmark = pytest.mark.anyio


# ---------- Helpers ---------------------------------------------------------


def _make_deps(
    *,
    cascaded_review_enabled: bool = False,
    cascade_short_circuit_on_stage_a: bool = True,
    cascade_short_circuit_on_stage_b: bool = True,
    cascade_short_circuit_on_stage_c: bool = False,
    traceability_mode: str = "off",
    pointwise_novelty_enabled: bool = False,
) -> PipelineDeps:
    config = PipelineConfig(
        anthropic_api_key="sk-test-fake-key",  # type: ignore[arg-type]
        model_name="test",
        tool_call_delay_seconds=0,
        cascaded_review_enabled=cascaded_review_enabled,
        cascade_short_circuit_on_stage_a=cascade_short_circuit_on_stage_a,
        cascade_short_circuit_on_stage_b=cascade_short_circuit_on_stage_b,
        cascade_short_circuit_on_stage_c=cascade_short_circuit_on_stage_c,
        traceability_mode=traceability_mode,  # type: ignore[arg-type]
        pointwise_novelty_enabled=pointwise_novelty_enabled,
    )
    return PipelineDeps.create(config=config)


class _RunCtx:
    """Minimal stand-in for GraphRunContext compatible with cascade nodes."""

    def __init__(self, state: ReviewState, deps: PipelineDeps) -> None:
        self.state = state
        self.deps = deps


def _persona(
    intention: Intention,
    overall_verdict: str = "accept",
    *,
    rejection_grounds_finding: bool = False,
) -> PersonaReviewOutput:
    findings: list[ReviewFinding] = []
    if rejection_grounds_finding:
        findings.append(
            ReviewFinding(
                finding_id="F1",
                severity="critical",
                section="Methods",
                description="Fatal methodological flaw.",
                rejection_grounds=True,
            )
        )
    return PersonaReviewOutput(
        persona=PersonaSpec(
            commitment=Commitment.THOROUGH,
            intention=intention,
            knowledgeability=Knowledgeability.DEEP_IN_FIELD,
            target_journal="JBI",
            target_acceptance_rate=0.20,
        ),
        findings=findings,
        overall_verdict=overall_verdict,  # type: ignore[arg-type]
        confidence=0.9,
        one_paragraph_summary="Persona review summary.",
    )


def _novelty(verdict: str, blockers: list[str] | None = None) -> NoveltyReport:
    return NoveltyReport(
        claims=[
            ContributionClaim(
                claim_id="C1",
                claim_text="X is novel because Y.",
                dimension=ClaimNoveltyDimension.NEW_METHOD,
                section="introduction",
                cited_traces=[],
            ),
        ],
        assessments=[
            ClaimAssessment(
                claim_id="C1",
                verdict=ClaimVerdict.NOVEL,
                nearest_prior_works=[],
                differentiation_note="No overlap.",
            ),
        ],
        overall_verdict=verdict,  # type: ignore[arg-type]
        rejection_blockers=blockers or [],
    )


# ---------- Models ----------------------------------------------------------


class TestCascadeModels:
    """StageResult / CascadeResult / ClaimAuditReport construction + frozen."""

    def test_stage_verdict_values(self) -> None:
        assert StageVerdict.PASS.value == "pass"
        assert StageVerdict.SHORT_CIRCUIT_REJECT.value == "short_circuit_reject"
        assert StageVerdict.SKIPPED.value == "skipped"
        assert StageVerdict.NOT_RUN.value == "not_run"

    def test_cascade_stage_name_values(self) -> None:
        assert CascadeStageName.NUMERICAL_GROUNDING.value == "numerical_grounding"
        assert CascadeStageName.NOVELTY.value == "novelty"
        assert CascadeStageName.METHODOLOGY.value == "methodology"
        assert CascadeStageName.NARRATIVE.value == "narrative"

    def test_stage_result_is_frozen(self) -> None:
        result = StageResult(
            stage=CascadeStageName.NOVELTY,
            verdict=StageVerdict.PASS,
        )
        with pytest.raises(ValidationError):
            result.verdict = StageVerdict.SHORT_CIRCUIT_REJECT  # type: ignore[misc]

    def test_cascade_result_is_frozen(self) -> None:
        result = CascadeResult(stages=[], final_verdict="accept")
        with pytest.raises(ValidationError):
            result.final_verdict = "reject"  # type: ignore[misc]

    def test_claim_audit_report_construction(self) -> None:
        report = ClaimAuditReport(
            findings=[
                ClaimAuditFinding(
                    finding_id="A1",
                    severity="critical",
                    description="Bare 23.5% in Results.",
                    offending_text="23.5% improvement",
                ),
            ],
            overall_grounding_pass=False,
            summary="1 critical finding.",
        )
        assert report.overall_grounding_pass is False
        assert len(report.findings) == 1
        assert report.findings[0].severity == "critical"


# ---------- Aggregation -----------------------------------------------------


class TestAggregateCascadeResult:
    """Pure-function tests for aggregate_cascade_result."""

    def test_all_pass_yields_accept(self) -> None:
        stages = [
            StageResult(stage=CascadeStageName.NUMERICAL_GROUNDING, verdict=StageVerdict.PASS),
            StageResult(stage=CascadeStageName.NOVELTY, verdict=StageVerdict.PASS),
            StageResult(stage=CascadeStageName.METHODOLOGY, verdict=StageVerdict.PASS),
            StageResult(stage=CascadeStageName.NARRATIVE, verdict=StageVerdict.PASS),
        ]
        result = aggregate_cascade_result(stages)
        assert result.final_verdict == "accept"
        assert result.rejection_stage is None
        assert len(result.stages) == 4

    def test_first_short_circuit_drives_rejection_stage(self) -> None:
        stages = [
            StageResult(
                stage=CascadeStageName.NUMERICAL_GROUNDING,
                verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
                gate_reason="3 bare numbers",
            ),
        ]
        result = aggregate_cascade_result(stages)
        assert result.final_verdict == "reject"
        assert result.rejection_stage == CascadeStageName.NUMERICAL_GROUNDING
        assert "3 bare numbers" in result.rejection_summary
        # Padded SKIPPED entries for stages B/C/D
        assert len(result.stages) == 4
        for s in result.stages[1:]:
            assert s.verdict == StageVerdict.SKIPPED

    def test_stage_b_rejection_pads_c_and_d_skipped(self) -> None:
        stages = [
            StageResult(stage=CascadeStageName.NUMERICAL_GROUNDING, verdict=StageVerdict.PASS),
            StageResult(
                stage=CascadeStageName.NOVELTY,
                verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
                gate_reason="Redundant claims",
            ),
        ]
        result = aggregate_cascade_result(stages)
        assert result.final_verdict == "reject"
        assert result.rejection_stage == CascadeStageName.NOVELTY
        assert result.stages[2].verdict == StageVerdict.SKIPPED
        assert result.stages[3].verdict == StageVerdict.SKIPPED

    def test_unvisited_trailing_stage_marked_not_run_when_no_rejection(self) -> None:
        # Only ran A and B, neither rejected.
        stages = [
            StageResult(stage=CascadeStageName.NUMERICAL_GROUNDING, verdict=StageVerdict.PASS),
            StageResult(stage=CascadeStageName.NOVELTY, verdict=StageVerdict.NOT_RUN),
        ]
        result = aggregate_cascade_result(stages)
        assert result.final_verdict == "accept"
        # C and D padded as NOT_RUN (no rejection seen).
        assert result.stages[2].verdict == StageVerdict.NOT_RUN
        assert result.stages[3].verdict == StageVerdict.NOT_RUN


# ---------- Stage A — numerical grounding ----------------------------------


class TestStageANumericalGrounding:
    """Stage A regex fallback paths (no LLM calls)."""

    async def test_passes_when_traceability_off(self) -> None:
        deps = _make_deps(traceability_mode="off")
        state = ReviewState(paper_draft={"title": "T", "content": "Improved by 23.5%."})
        ctx = _RunCtx(state, deps)
        result = await run_numerical_grounding_stage(ctx, "Improved by 23.5%.")
        assert result.verdict == StageVerdict.PASS
        assert result.stage == CascadeStageName.NUMERICAL_GROUNDING

    async def test_short_circuits_on_bare_numbers_when_traceability_partial(self) -> None:
        # Spec 1 partial mode + bare number prose + no auditor agent path
        # (no pipeline_state ref → falls into regex branch).
        deps = _make_deps(traceability_mode="partial")
        state = ReviewState(paper_draft={"title": "T", "content": "AUC 0.87 in test."})
        ctx = _RunCtx(state, deps)
        result = await run_numerical_grounding_stage(ctx, "AUC 0.87 in test.")
        assert result.verdict == StageVerdict.SHORT_CIRCUIT_REJECT
        assert result.gate_reason is not None
        assert "regex fallback" in result.gate_reason

    async def test_passes_when_short_circuit_disabled_even_with_bare_numbers(self) -> None:
        deps = _make_deps(
            traceability_mode="partial",
            cascade_short_circuit_on_stage_a=False,
        )
        state = ReviewState(paper_draft={"title": "T", "content": "AUC 0.87."})
        ctx = _RunCtx(state, deps)
        result = await run_numerical_grounding_stage(ctx, "AUC 0.87.")
        assert result.verdict == StageVerdict.PASS


# ---------- Stage B — novelty ----------------------------------------------


class TestStageBNovelty:
    """Stage B reads state.novelty_report (Spec 4 output)."""

    async def test_not_run_when_novelty_report_absent(self) -> None:
        deps = _make_deps()
        state = ReviewState()
        ctx = _RunCtx(state, deps)
        result = await run_novelty_stage(ctx)
        assert result.verdict == StageVerdict.NOT_RUN

    async def test_passes_when_novelty_pass(self) -> None:
        deps = _make_deps()
        state = ReviewState(novelty_report=_novelty("PASS"))
        ctx = _RunCtx(state, deps)
        result = await run_novelty_stage(ctx)
        assert result.verdict == StageVerdict.PASS

    async def test_short_circuits_on_reject_novelty(self) -> None:
        deps = _make_deps()
        state = ReviewState(novelty_report=_novelty("REJECT_NOVELTY", blockers=["C1"]))
        ctx = _RunCtx(state, deps)
        result = await run_novelty_stage(ctx)
        assert result.verdict == StageVerdict.SHORT_CIRCUIT_REJECT
        assert result.gate_reason is not None
        assert "C1" in result.gate_reason

    async def test_passes_when_short_circuit_disabled(self) -> None:
        deps = _make_deps(cascade_short_circuit_on_stage_b=False)
        state = ReviewState(novelty_report=_novelty("REJECT_NOVELTY", blockers=["C1"]))
        ctx = _RunCtx(state, deps)
        result = await run_novelty_stage(ctx)
        assert result.verdict == StageVerdict.PASS


# ---------- Stage C — methodology ------------------------------------------


class TestStageCMethodology:
    """Stage C reads state.persona_reviews (Spec 5 output)."""

    async def test_not_run_when_persona_reviews_empty(self) -> None:
        deps = _make_deps()
        state = ReviewState()
        ctx = _RunCtx(state, deps)
        result = await run_methodology_stage(ctx)
        assert result.verdict == StageVerdict.NOT_RUN

    async def test_passes_when_no_gating_persona_rejects(self) -> None:
        deps = _make_deps(cascade_short_circuit_on_stage_c=True)
        state = ReviewState(
            persona_reviews=[
                _persona(Intention.SKEPTICAL_GATEKEEPER, overall_verdict="accept"),
                _persona(Intention.APPLIED_PRACTITIONER, overall_verdict="reject"),  # not gating
            ]
        )
        ctx = _RunCtx(state, deps)
        result = await run_methodology_stage(ctx)
        assert result.verdict == StageVerdict.PASS

    async def test_short_circuits_when_gatekeeper_rejects_with_grounds(self) -> None:
        deps = _make_deps(cascade_short_circuit_on_stage_c=True)
        state = ReviewState(
            persona_reviews=[
                _persona(
                    Intention.SKEPTICAL_GATEKEEPER,
                    overall_verdict="reject",
                    rejection_grounds_finding=True,
                ),
            ]
        )
        ctx = _RunCtx(state, deps)
        result = await run_methodology_stage(ctx)
        assert result.verdict == StageVerdict.SHORT_CIRCUIT_REJECT
        assert result.gate_reason is not None
        assert "skeptical_gatekeeper" in result.gate_reason

    async def test_passes_when_short_circuit_disabled_even_with_rejection(self) -> None:
        # Default cascade_short_circuit_on_stage_c=False per spec.
        deps = _make_deps()
        state = ReviewState(
            persona_reviews=[
                _persona(
                    Intention.DOMAIN_PURIST,
                    overall_verdict="reject",
                    rejection_grounds_finding=True,
                ),
            ]
        )
        ctx = _RunCtx(state, deps)
        result = await run_methodology_stage(ctx)
        # Stage records the rejection in artifacts but does not short-circuit.
        assert result.verdict == StageVerdict.PASS
        assert "domain_purist" in result.artifacts.get("non_short_circuited_rejections", [])


# ---------- Stage D — narrative --------------------------------------------


class TestStageDNarrative:
    """Stage D is terminal; always PASS in Phase 1."""

    async def test_always_passes(self) -> None:
        deps = _make_deps()
        state = ReviewState()
        ctx = _RunCtx(state, deps)
        result = await run_narrative_stage(ctx, "Some manuscript text.")
        assert result.verdict == StageVerdict.PASS
        assert result.stage == CascadeStageName.NARRATIVE


# ---------- Routing — PointWiseNoveltyReviewerNode -------------------------


class TestRoutingFromPointwise:
    """When cascaded_review_enabled is on, pointwise routes to CascadedReviewNode."""

    async def test_routes_to_editorial_when_cascade_off(self) -> None:
        deps = _make_deps(cascaded_review_enabled=False, pointwise_novelty_enabled=False)
        state = ReviewState(paper_draft={"title": "T", "content": "Body."})
        ctx = _RunCtx(state, deps)
        node = PointWiseNoveltyReviewerNode()
        result = await node.run(ctx)  # type: ignore[arg-type]
        assert isinstance(result, EditorialSynthesizerNode)
        assert state.cascade_result is None

    async def test_routes_to_cascade_when_flag_on(self) -> None:
        deps = _make_deps(cascaded_review_enabled=True, pointwise_novelty_enabled=False)
        state = ReviewState(paper_draft={"title": "T", "content": "Body."})
        ctx = _RunCtx(state, deps)
        node = PointWiseNoveltyReviewerNode()
        result = await node.run(ctx)  # type: ignore[arg-type]
        assert isinstance(result, CascadedReviewNode)


# ---------- CascadedReviewNode integration ---------------------------------


class TestCascadedReviewNode:
    """End-to-end node behaviour (no real LLM calls)."""

    async def test_all_pass_with_no_specs_enabled(self) -> None:
        # Defaults: traceability off, no novelty_report, no persona_reviews.
        # Stage A → PASS (no traceability), B → NOT_RUN, C → NOT_RUN, D → PASS.
        deps = _make_deps(cascaded_review_enabled=True)
        state = ReviewState(paper_draft={"title": "T", "content": "Plain prose."})
        ctx = _RunCtx(state, deps)
        node = CascadedReviewNode()
        result = await node.run(ctx)  # type: ignore[arg-type]
        assert isinstance(result, EditorialSynthesizerNode)
        assert state.cascade_result is not None
        assert state.cascade_result.final_verdict == "accept"
        assert state.cascade_result.rejection_stage is None
        # All 4 stages present in canonical order.
        names = [s.stage for s in state.cascade_result.stages]
        assert names == [
            CascadeStageName.NUMERICAL_GROUNDING,
            CascadeStageName.NOVELTY,
            CascadeStageName.METHODOLOGY,
            CascadeStageName.NARRATIVE,
        ]

    async def test_short_circuits_at_stage_b_on_reject_novelty(self) -> None:
        # Stage A passes (traceability off), Stage B sees REJECT_NOVELTY → reject.
        deps = _make_deps(cascaded_review_enabled=True)
        state = ReviewState(
            paper_draft={"title": "T", "content": "Body."},
            novelty_report=_novelty("REJECT_NOVELTY", blockers=["C1", "C2"]),
        )
        ctx = _RunCtx(state, deps)
        node = CascadedReviewNode()
        await node.run(ctx)  # type: ignore[arg-type]
        assert state.cascade_result is not None
        assert state.cascade_result.final_verdict == "reject"
        assert state.cascade_result.rejection_stage == CascadeStageName.NOVELTY
        # Stages C and D padded as SKIPPED.
        c_result = next(
            s for s in state.cascade_result.stages
            if s.stage == CascadeStageName.METHODOLOGY
        )
        d_result = next(
            s for s in state.cascade_result.stages
            if s.stage == CascadeStageName.NARRATIVE
        )
        assert c_result.verdict == StageVerdict.SKIPPED
        assert d_result.verdict == StageVerdict.SKIPPED
        # System message logged about the rejection.
        assert any(
            "SHORT-CIRCUIT REJECT" in (m.get("content") or "")
            for m in state.messages
        )

    async def test_stage_a_short_circuits_skip_b_c_d(self) -> None:
        # traceability=partial + bare-number prose → Stage A regex rejects.
        deps = _make_deps(
            cascaded_review_enabled=True,
            traceability_mode="partial",
        )
        state = ReviewState(
            paper_draft={"title": "T", "content": "AUC was 0.87 in evaluation."},
            # Even though novelty_report present, B should be SKIPPED.
            novelty_report=_novelty("PASS"),
        )
        ctx = _RunCtx(state, deps)
        node = CascadedReviewNode()
        await node.run(ctx)  # type: ignore[arg-type]
        assert state.cascade_result is not None
        assert state.cascade_result.final_verdict == "reject"
        assert state.cascade_result.rejection_stage == CascadeStageName.NUMERICAL_GROUNDING
        # B/C/D all SKIPPED (only A ran).
        skipped = [
            s for s in state.cascade_result.stages
            if s.verdict == StageVerdict.SKIPPED
        ]
        assert len(skipped) == 3


# ---------- ReviewState carries cascade_result -----------------------------


def test_review_state_has_cascade_result_field() -> None:
    state = ReviewState()
    assert hasattr(state, "cascade_result")
    assert state.cascade_result is None


def test_review_state_accepts_cascade_result_assignment() -> None:
    state = ReviewState()
    state.cascade_result = CascadeResult(stages=[], final_verdict="accept")
    assert state.cascade_result is not None
    assert state.cascade_result.final_verdict == "accept"
