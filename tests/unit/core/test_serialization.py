"""Test that state dataclasses with typed Pydantic models survive TypeAdapter serialization."""

from __future__ import annotations

from pydantic import TypeAdapter

from academic_pipeline.models.shared import Source
from academic_pipeline.models.research import (
    Bibliography,
    FINERScores,
    RQBrief,
    Scope,
    SearchStrategy,
    SynthesisReport,
    Theme,
)
from academic_pipeline.models.integrity import (
    IntegrityReport,
    IssueCounts,
    PhaseAReferences,
    PhaseBCitationContext,
    PhaseCData,
    PhaseDOriginality,
    PhaseEClaims,
    PhaseResult,
)
from academic_pipeline.pipeline.state import PipelineState


def _make_rq_brief() -> RQBrief:
    return RQBrief(
        research_question="What is X?",
        sub_questions=["Sub Q1", "Sub Q2"],
        finer_scores=FINERScores(feasible=4, interesting=4, novel=4, ethical=5, relevant=4),
        scope=Scope(
            in_scope=["A"], out_of_scope=["B"],
            domain="CS", timeframe="2020-2025", geography="Global", population="Researchers",
        ),
        methodology_type="quantitative",
        theoretical_framework="Grounded theory",
        keywords=["a", "b", "c", "d", "e"],
    )


def _make_bibliography() -> Bibliography:
    return Bibliography(
        sources=[
            Source(
                id="s1", title="Paper A", authors=["Smith"], year=2024,
                citation="Smith (2024)", source_type="journal_article",
                evidence_tier=1, quality_tier="tier_1", relevance="core",
                relevance_score=9, annotation="Key paper",
            ),
        ],
        search_strategy=SearchStrategy(
            databases=["PubMed"], keywords=["AI"],
            inclusion_criteria=["English"], exclusion_criteria=["Non-peer-reviewed"],
            date_range="2020-2025",
        ),
        coverage_assessment="Good coverage",
        minimum_sources=10,
    )


def _make_synthesis() -> SynthesisReport:
    return SynthesisReport(
        themes=[
            Theme(name="T1", description="Desc", supporting_sources=["s1"], strength="strong"),
            Theme(name="T2", description="Desc2", supporting_sources=["s1"], strength="moderate"),
            Theme(name="T3", description="Desc3", supporting_sources=["s1"], strength="emerging"),
        ],
        research_gaps=["Gap 1"],
        key_debates=[],
        methodology_recommendations=["Use RCTs"],
        theoretical_implications=["Extends theory X"],
        consensus_areas=["AI is useful"],
    )


def _make_integrity_report() -> IntegrityReport:
    return IntegrityReport(
        verdict="PASS",
        phases=PhaseResult(
            A_references=PhaseAReferences(checked=10, passed=10, failed=0),
            B_citation_context=PhaseBCitationContext(sampled=5, verified=5),
            C_data=PhaseCData(claims_checked=3, verified=3),
            D_originality=PhaseDOriginality(checked=True),
            E_claims=PhaseEClaims(checked=3, verified=3),
        ),
        overall_issues=IssueCounts(SERIOUS=0, MEDIUM=0, MINOR=0),
        citation_integrity_score=0.95,
        fabrication_risk_score=0.05,
    )


class TestPipelineStateSerialization:
    def test_rq_brief_round_trip(self) -> None:
        state = PipelineState(topic="test", rq_brief=_make_rq_brief())
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.rq_brief is not None
        assert restored.rq_brief.research_question == "What is X?"

    def test_bibliography_round_trip(self) -> None:
        state = PipelineState(topic="test", bibliography=_make_bibliography())
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.bibliography is not None
        assert len(restored.bibliography.sources) == 1

    def test_synthesis_round_trip(self) -> None:
        state = PipelineState(topic="test", synthesis=_make_synthesis())
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.synthesis is not None
        assert len(restored.synthesis.themes) == 3

    def test_integrity_report_round_trip(self) -> None:
        state = PipelineState(topic="test", integrity_report={"verdict": "PASS", "raw": "ok"})
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.integrity_report["verdict"] == "PASS"

    def test_full_state_round_trip(self) -> None:
        state = PipelineState(
            topic="Full test",
            rq_brief=_make_rq_brief(),
            bibliography=_make_bibliography(),
            synthesis=_make_synthesis(),
            integrity_report={"verdict": "PASS"},
        )
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.topic == "Full test"
        assert restored.rq_brief is not None
        assert restored.bibliography is not None
        assert restored.synthesis is not None
        assert restored.integrity_report["verdict"] == "PASS"

    def test_none_fields_round_trip(self) -> None:
        state = PipelineState(topic="empty")
        adapter = TypeAdapter(PipelineState)
        json_bytes = adapter.dump_json(state)
        restored = adapter.validate_json(json_bytes)
        assert restored.rq_brief is None
        assert restored.bibliography is None
