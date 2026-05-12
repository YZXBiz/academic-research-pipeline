"""Unit tests for the point-wise novelty reviewer (SCI Spec 4 Phase 1)."""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

import pydantic_core
import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel, _JsonSchemaTestData

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.novelty_gate import NeighborPaper
from academic_pipeline.models.novelty_report import (
    ClaimAssessment,
    ClaimNoveltyDimension,
    ClaimVerdict,
    ContributionClaim,
    ContributionClaimList,
    NoveltyReport,
)
from academic_pipeline.review.agents import agents as _agents
from academic_pipeline.review.graph import (
    EditorialSynthesizerNode,
    PointWiseNoveltyReviewerNode,
)
from academic_pipeline.review.novelty_aggregation import aggregate_novelty_report
from academic_pipeline.review.state import ReviewState


pytestmark = pytest.mark.anyio


# ---------- Models -----------------------------------------------------------


class TestModels:
    """Models construct correctly and are frozen."""

    def test_contribution_claim_construction(self) -> None:
        claim = ContributionClaim(
            claim_id="C1",
            claim_text="X is novel because Y",
            dimension=ClaimNoveltyDimension.NEW_METHOD,
            section="introduction",
            cited_traces=["⟨num:auc_test⟩"],
        )
        assert claim.claim_id == "C1"
        assert claim.dimension is ClaimNoveltyDimension.NEW_METHOD

    def test_contribution_claim_is_frozen(self) -> None:
        claim = ContributionClaim(
            claim_id="C1",
            claim_text="X is novel because Y",
            dimension=ClaimNoveltyDimension.NEW_METHOD,
            section="introduction",
        )
        with pytest.raises(ValidationError):
            claim.claim_id = "C2"  # type: ignore[misc]

    def test_novelty_report_is_frozen(self) -> None:
        report = NoveltyReport(
            claims=[],
            assessments=[],
            overall_verdict="PASS",
            rejection_blockers=[],
        )
        with pytest.raises(ValidationError):
            report.overall_verdict = "REVISE"  # type: ignore[misc]


# ---------- Aggregation -------------------------------------------------------


def _claim(cid: str) -> ContributionClaim:
    return ContributionClaim(
        claim_id=cid,
        claim_text=f"{cid} is novel because reasons",
        dimension=ClaimNoveltyDimension.NEW_METHOD,
        section="introduction",
    )


def _assessment(cid: str, verdict: ClaimVerdict) -> ClaimAssessment:
    return ClaimAssessment(
        claim_id=cid,
        verdict=verdict,
        nearest_prior_works=[],
        differentiation_note=f"{cid} note",
    )


@pytest.mark.parametrize(
    ("verdicts", "expected_overall", "expected_blockers"),
    [
        (
            [ClaimVerdict.NOVEL, ClaimVerdict.NOVEL, ClaimVerdict.NOVEL],
            "PASS",
            [],
        ),
        (
            [ClaimVerdict.NOVEL, ClaimVerdict.PARTIAL_OVERLAP, ClaimVerdict.NOVEL],
            "REVISE",
            [],
        ),
        (
            [ClaimVerdict.NOVEL, ClaimVerdict.PARTIAL_OVERLAP, ClaimVerdict.REDUNDANT],
            "REJECT_NOVELTY",
            ["C3"],
        ),
        (
            [ClaimVerdict.REDUNDANT, ClaimVerdict.REDUNDANT],
            "REJECT_NOVELTY",
            ["C1", "C2"],
        ),
    ],
)
def test_aggregate_novelty_report(
    verdicts: list[ClaimVerdict],
    expected_overall: str,
    expected_blockers: list[str],
) -> None:
    cids = [f"C{i + 1}" for i in range(len(verdicts))]
    claims = [_claim(c) for c in cids]
    assessments = [_assessment(c, v) for c, v in zip(cids, verdicts, strict=True)]
    report = aggregate_novelty_report(claims, assessments)
    assert report.overall_verdict == expected_overall
    assert report.rejection_blockers == expected_blockers
    assert report.claims == claims
    assert report.assessments == assessments


# ---------- Node --------------------------------------------------------------


def _make_deps(*, pointwise_novelty_enabled: bool, top_n: int = 5) -> PipelineDeps:
    config = PipelineConfig(
        anthropic_api_key="sk-test-fake-key",  # type: ignore[arg-type]
        model_name="test",
        tool_call_delay_seconds=0,
        pointwise_novelty_enabled=pointwise_novelty_enabled,
        pointwise_novelty_top_n_per_claim=top_n,
    )
    return PipelineDeps.create(config=config)


def _json_for(model_cls: type) -> str:
    schema = model_cls.model_json_schema()
    data = _JsonSchemaTestData(schema, 0).generate()
    return pydantic_core.to_json(data).decode()


@contextlib.contextmanager
def _override_pointwise_agents(claims_json: str, assessment_json: str) -> contextlib.AbstractContextManager[None]:
    """Override the two new agents with TestModels returning canned JSON."""
    stack = contextlib.ExitStack()
    stack.enter_context(
        _agents["claim_extractor"].override(
            model=TestModel(custom_output_text=claims_json, call_tools=[]),
        )
    )
    stack.enter_context(
        _agents["claim_novelty_assessor"].override(
            model=TestModel(custom_output_text=assessment_json, call_tools=[]),
        )
    )
    try:
        yield
    finally:
        stack.close()


class _RunCtx:
    """Minimal stand-in for GraphRunContext compatible with the node body."""

    def __init__(self, state: ReviewState, deps: PipelineDeps) -> None:
        self.state = state
        self.deps = deps


async def test_node_skips_when_flag_off() -> None:
    """When config.pointwise_novelty_enabled is false, the node returns
    EditorialSynthesizerNode with no S2 calls and no agent calls."""
    deps = _make_deps(pointwise_novelty_enabled=False)
    state = ReviewState(paper_draft={"title": "T", "content": "Body"})
    node = PointWiseNoveltyReviewerNode()

    with patch(
        "academic_pipeline.tools.bibliography.semantic_scholar.search_s2_by_title"
    ) as mock_s2:
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, EditorialSynthesizerNode)
    assert state.novelty_report is None
    assert mock_s2.call_count == 0


async def test_node_skips_on_empty_manuscript() -> None:
    """An empty paper_draft short-circuits the node without any S2 or agent
    calls."""
    deps = _make_deps(pointwise_novelty_enabled=True)
    state = ReviewState(paper_draft=None)
    node = PointWiseNoveltyReviewerNode()

    with patch(
        "academic_pipeline.tools.bibliography.semantic_scholar.search_s2_by_title"
    ) as mock_s2:
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, EditorialSynthesizerNode)
    assert state.novelty_report is None
    assert mock_s2.call_count == 0


async def test_node_populates_state_when_flag_on() -> None:
    """End-to-end: 2 claims → S2 called twice → assessor called twice → report populated."""
    deps = _make_deps(pointwise_novelty_enabled=True, top_n=3)
    state = ReviewState(
        paper_draft={
            "title": "Diabetes prediction in CKD-comorbid patients",
            "abstract": "We propose XGBoost for diabetes prediction.",
            "content": "Body of the paper.",
        }
    )

    claims = ContributionClaimList(
        claims=[
            ContributionClaim(
                claim_id="C1",
                claim_text="XGBoost is novel because outperforms baselines on CKD subpopulation",
                dimension=ClaimNoveltyDimension.NEW_METHOD,
                section="introduction",
            ),
            ContributionClaim(
                claim_id="C2",
                claim_text="Feature importance result is novel because dominant predictor identified",
                dimension=ClaimNoveltyDimension.NEW_RESULT,
                section="results",
            ),
        ]
    )
    assessment = ClaimAssessment(
        claim_id="C1",
        verdict=ClaimVerdict.NOVEL,
        nearest_prior_works=[],
        differentiation_note="No overlapping prior work in retrieved set.",
    )
    s2_payload = json.dumps(
        {
            "query": "anything",
            "matches": [
                {
                    "paperId": "p1",
                    "title": "Some prior work",
                    "doi": "10.0/abc",
                    "similarity": 0.42,
                    "abstract": "Old abstract",
                }
            ],
        }
    )

    with patch(
        "academic_pipeline.tools.bibliography.semantic_scholar.search_s2_by_title",
        return_value=s2_payload,
    ) as mock_s2, _override_pointwise_agents(
        claims.model_dump_json(), assessment.model_dump_json()
    ):
        node = PointWiseNoveltyReviewerNode()
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, EditorialSynthesizerNode)
    assert state.novelty_report is not None
    assert len(state.novelty_report.claims) == 2
    assert len(state.novelty_report.assessments) == 2
    # All NOVEL → overall PASS
    assert state.novelty_report.overall_verdict == "PASS"
    assert mock_s2.call_count == 2


async def test_node_handles_s2_failure_gracefully() -> None:
    """When S2 raises, the node still completes by passing empty neighbors to
    the assessor; the report is still populated."""
    deps = _make_deps(pointwise_novelty_enabled=True)
    state = ReviewState(
        paper_draft={"title": "T", "abstract": "A", "content": "Body"}
    )
    claims = ContributionClaimList(
        claims=[
            ContributionClaim(
                claim_id="C1",
                claim_text="X is novel because Y",
                dimension=ClaimNoveltyDimension.NEW_METHOD,
                section="introduction",
            )
        ]
    )
    assessment = ClaimAssessment(
        claim_id="C1",
        verdict=ClaimVerdict.NOVEL,
        nearest_prior_works=[],
        differentiation_note="No prior work returned.",
    )

    with patch(
        "academic_pipeline.tools.bibliography.semantic_scholar.search_s2_by_title",
        side_effect=RuntimeError("network down"),
    ), _override_pointwise_agents(
        claims.model_dump_json(), assessment.model_dump_json()
    ):
        node = PointWiseNoveltyReviewerNode()
        result = await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert isinstance(result, EditorialSynthesizerNode)
    assert state.novelty_report is not None
    assert state.novelty_report.overall_verdict == "PASS"
    assert state.novelty_report.assessments[0].verdict is ClaimVerdict.NOVEL


async def test_node_records_reject_blocker_message() -> None:
    """When at least one assessment is REDUNDANT, the node appends a
    system message naming the blockers and the report verdict is
    REJECT_NOVELTY."""
    deps = _make_deps(pointwise_novelty_enabled=True)
    state = ReviewState(
        paper_draft={"title": "T", "abstract": "A", "content": "Body"}
    )
    claims = ContributionClaimList(
        claims=[
            ContributionClaim(
                claim_id="C1",
                claim_text="X is novel because Y",
                dimension=ClaimNoveltyDimension.NEW_METHOD,
                section="introduction",
            )
        ]
    )
    assessment = ClaimAssessment(
        claim_id="C1",
        verdict=ClaimVerdict.REDUNDANT,
        nearest_prior_works=[
            NeighborPaper(
                title="Smith 2024 — same contribution",
                doi=None,
                semantic_scholar_id=None,
                similarity=0.94,
                abstract_excerpt="",
            )
        ],
        differentiation_note="Smith 2024 already does this.",
    )
    s2_payload = json.dumps({"query": "x", "matches": []})

    with patch(
        "academic_pipeline.tools.bibliography.semantic_scholar.search_s2_by_title",
        return_value=s2_payload,
    ), _override_pointwise_agents(
        claims.model_dump_json(), assessment.model_dump_json()
    ):
        node = PointWiseNoveltyReviewerNode()
        await node.run(_RunCtx(state, deps))  # type: ignore[arg-type]

    assert state.novelty_report is not None
    assert state.novelty_report.overall_verdict == "REJECT_NOVELTY"
    assert state.novelty_report.rejection_blockers == ["C1"]
    assert any(
        m.get("role") == "system" and "REJECT_NOVELTY" in m.get("content", "")
        for m in state.messages
    )
