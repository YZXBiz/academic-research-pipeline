"""Tests for all 10 Pydantic schema models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from academic_pipeline.models.shared import (
    EvaluationResult,
    Source,
)
from academic_pipeline.models.research import (
    FINERScores,
    RQBrief,
    Scope,
    SynthesisReport,
    Theme,
)
from academic_pipeline.models.writing import (
    CitationStyleMetrics,
    ParagraphLength,
    SentenceLength,
    StyleProfile,
    VocabularyPreferences,
)
from academic_pipeline.models.review import (
    DimensionScore,
    EditorDimensionScore,
    EditorReview,
    ResponseItem,
    ReviewIssue,
    ReviewReport,
    ReviewerReport,
    RevisionContext,
)
from academic_pipeline.models.integrity import (
    IntegrityReport,
    IssueCounts,
    MaterialPassport,
    PhaseAReferences,
    PhaseBCitationContext,
    PhaseCData,
    PhaseDOriginality,
    PhaseEClaims,
    PhaseResult,
)
from academic_pipeline.core.enums import (
    EditorialDecision,
    IssueSeverity,
    ReviewDimension,
    RevisionSource,
)


class TestFINERScores:
    def test_valid_scores(self):
        scores = FINERScores(feasible=4, interesting=5, novel=4, ethical=5, relevant=5)
        assert scores.feasible == 4
        assert scores.average == 4.6

    def test_below_minimum(self):
        with pytest.raises(ValueError):
            FINERScores(feasible=2, interesting=5, novel=4, ethical=5, relevant=5)

    def test_out_of_range_high(self):
        with pytest.raises(ValueError):
            FINERScores(feasible=6, interesting=5, novel=4, ethical=5, relevant=5)

    def test_out_of_range_low(self):
        with pytest.raises(ValueError):
            FINERScores(feasible=0, interesting=5, novel=4, ethical=5, relevant=5)


class TestRQBrief:
    def test_valid_rq_brief(self):
        brief = RQBrief(
            research_question="How does X affect Y?",
            sub_questions=["What is X?", "What is Y?"],
            finer_scores=FINERScores(feasible=4, interesting=5, novel=4, ethical=5, relevant=5),
            scope=Scope(
                in_scope=["A"],
                out_of_scope=["B"],
                domain="CS",
                timeframe="2020-2025",
                geography="Global",
                population="Students",
            ),
            methodology_type="mixed",
            theoretical_framework="TAM",
            keywords=["a", "b", "c", "d", "e"],
        )
        assert brief.research_question == "How does X affect Y?"

    def test_too_few_keywords(self):
        with pytest.raises(ValueError):
            RQBrief(
                research_question="Q?",
                sub_questions=["A?", "B?"],
                finer_scores=FINERScores(feasible=4, interesting=5, novel=4, ethical=5, relevant=5),
                scope=Scope(
                    in_scope=["A"], out_of_scope=["B"], domain="CS", timeframe="2020", geography="G", population="P"
                ),
                methodology_type="mixed",
                theoretical_framework="TAM",
                keywords=["a", "b"],
            )


class TestBibliography:
    def test_valid_source(self):
        source = Source(
            id="S01",
            title="Test Paper",
            authors=["Smith, J."],
            year=2023,
            doi="10.1234/test",
            citation="Smith (2023)...",
            type="journal_article",
            evidence_tier=2,
            quality_tier="tier_1",
            relevance="core",
            relevance_score=9,
            annotation="Important paper.",
        )
        assert source.evidence_tier == 2

    def test_invalid_evidence_tier(self):
        with pytest.raises(ValueError):
            Source(
                id="S01",
                title="T",
                authors=["A"],
                year=2023,
                citation="C",
                type="journal_article",
                evidence_tier=8,
                quality_tier="tier_1",
                relevance="core",
                relevance_score=5,
                annotation="A",
            )


class TestSynthesisReport:
    def test_min_themes(self):
        with pytest.raises(ValueError):
            SynthesisReport(
                themes=[
                    Theme(name="T1", description="D", supporting_sources=["S01"], strength="strong"),
                    Theme(name="T2", description="D", supporting_sources=["S02"], strength="moderate"),
                ],
                research_gaps=["G1"],
                key_debates=[],
                methodology_recommendations=["M1"],
                theoretical_implications=["I1"],
                consensus_areas=["C1"],
            )


class TestIntegrityReport:
    def test_blocks_pipeline(self):
        report = IntegrityReport(
            verdict="FAIL",
            phase="preint",
            phases=PhaseResult(
                references=PhaseAReferences(checked=10, passed=8, failed=2),
                citation_context=PhaseBCitationContext(sampled=5, verified=3),
                data=PhaseCData(claims_checked=10, verified=8),
                originality=PhaseDOriginality(checked=True),
                claims=PhaseEClaims(checked=10, verified=9),
            ),
            overall_issues=IssueCounts(serious=1, medium=1, minor=2),
            citation_integrity_score=0.7,
            fabrication_risk_score=0.3,
        )
        assert report.blocks_pipeline() is True

    def test_pass_does_not_block(self):
        report = IntegrityReport(
            verdict="PASS",
            phase="preint",
            phases=PhaseResult(
                references=PhaseAReferences(checked=10, passed=10, failed=0),
                citation_context=PhaseBCitationContext(sampled=5, verified=5),
                data=PhaseCData(claims_checked=10, verified=10),
                originality=PhaseDOriginality(checked=True),
                claims=PhaseEClaims(checked=10, verified=10),
            ),
            overall_issues=IssueCounts(serious=0, medium=0, minor=1),
            citation_integrity_score=0.95,
            fabrication_risk_score=0.0,
        )
        assert report.blocks_pipeline() is False


class TestReviewReport:
    def test_weighted_score(self):
        report = ReviewReport(
            editorial_decision="Minor Revision",
            reviewer_reports=[
                ReviewerReport(
                    reviewer_id="EIC",
                    role="Editor",
                    dimension_scores=[
                        DimensionScore(dimension="Originality", weight=0.2, score=80),
                        DimensionScore(dimension="Rigor", weight=0.25, score=70),
                    ],
                ),
            ],
            consensus="CONSENSUS-3",
            confidence_score=75,
        )
        expected = (80 * 0.2 + 70 * 0.25) / (0.2 + 0.25)
        assert abs(report.weighted_score() - expected) < 0.01


class TestResponseToReviewers:
    def test_decline_requires_justification(self):
        with pytest.raises(ValueError, match="decline_justification"):
            ResponseItem(
                roadmap_item_id="REV-001",
                reviewer_comment="Fix this",
                author_response="No",
                change_location="Section 3",
                status="DELIBERATE_LIMITATION",
            )

    def test_resolved_no_justification_needed(self):
        item = ResponseItem(
            roadmap_item_id="REV-001",
            reviewer_comment="Fix this",
            author_response="Fixed",
            change_location="Section 3",
            status="RESOLVED",
        )
        assert item.status == "RESOLVED"


class TestMaterialPassport:
    def test_fresh_passport(self):
        passport = MaterialPassport(
            origin_skill="research",
            verification_status="VERIFIED",
            version_label="research_v1",
            integrity_pass_date=datetime.now(UTC),
        )
        assert passport.can_skip_pre_review_integrity

    def test_stale_passport(self):
        from datetime import timedelta

        old_date = datetime.now(UTC) - timedelta(hours=25)
        passport = MaterialPassport(
            origin_skill="writing",
            verification_status="VERIFIED",
            version_label="paper_v1",
            integrity_pass_date=old_date,
        )
        assert passport.is_stale
        assert not passport.can_skip_pre_review_integrity


class TestStyleProfile:
    def test_valid_profile(self):
        profile = StyleProfile(
            calibration_source=["paper1.pdf", "paper2.pdf", "paper3.pdf"],
            sample_count=3,
            sentence_length=SentenceLength(mean=22.0, stddev=8.0, rhythm_pattern="variable"),
            paragraph_length=ParagraphLength(mean_sentences=5.0, variation="moderate"),
            vocabulary_preferences=VocabularyPreferences(formality="moderate-formal"),
            citation_style=CitationStyleMetrics(
                narrative_ratio=0.4,
                parenthetical_ratio=0.6,
                density=2.3,
            ),
            modifier_style="minimal",
        )
        assert profile.sample_count == 3


# --- Coverage: PRISMACounts.check_funnel validation error (lines 137-139) ---


class TestPRISMACounts:
    def test_invalid_funnel_order(self):
        from academic_pipeline.models.research import PRISMACounts

        with pytest.raises(ValueError, match="decreasing funnel"):
            PRISMACounts(identified=5, screened=10, eligible=3, included=1)


# --- Coverage: ResponseToReviewers._count_by_status and properties (lines 474-494) ---


class TestResponseToReviewersCountProperties:
    def test_count_properties(self):
        from academic_pipeline.models.review import ResponseToReviewers

        items = [
            ResponseItem(
                roadmap_item_id="R1",
                reviewer_comment="Fix",
                author_response="Fixed",
                change_location="S1",
                status="RESOLVED",
            ),
            ResponseItem(
                roadmap_item_id="R2",
                reviewer_comment="Fix",
                author_response="Cannot",
                change_location="S2",
                status="DELIBERATE_LIMITATION",
                decline_justification="Out of scope",
            ),
            ResponseItem(
                roadmap_item_id="R3",
                reviewer_comment="Fix",
                author_response="Impossible",
                change_location="S3",
                status="UNRESOLVABLE",
                decline_justification="Data not available",
            ),
            ResponseItem(
                roadmap_item_id="R4",
                reviewer_comment="Fix",
                author_response="Disagree",
                change_location="S4",
                status="REVIEWER_DISAGREE",
                decline_justification="Methodology is sound",
            ),
        ]
        rtr = ResponseToReviewers(revision_round=1, items=items)
        assert rtr.resolved_count == 1
        assert rtr.limitations_count == 1
        assert rtr.unresolvable_count == 1
        assert rtr.disagreed_count == 1


# --- Coverage: MaterialPassport.is_stale when integrity_pass_date is None (line 675) ---


class TestMaterialPassportNoneDate:
    def test_is_stale_when_no_integrity_pass_date(self):
        passport = MaterialPassport(
            origin_skill="research",
            verification_status="UNVERIFIED",
            version_label="v1",
            integrity_pass_date=None,
        )
        assert passport.is_stale is True


# ---------------------------------------------------------------------------
# Revision loop enums and models
# ---------------------------------------------------------------------------


class TestReviewDimension:
    def test_values(self) -> None:
        assert ReviewDimension.ORIGINALITY == "originality"
        assert ReviewDimension.METHODOLOGY == "methodology"
        assert ReviewDimension.EVIDENCE == "evidence"
        assert ReviewDimension.COHERENCE == "coherence"
        assert ReviewDimension.WRITING == "writing"

    def test_all_members(self) -> None:
        assert len(ReviewDimension) == 5


class TestIssueSeverity:
    def test_values(self) -> None:
        assert IssueSeverity.CRITICAL == "critical"
        assert IssueSeverity.MAJOR == "major"
        assert IssueSeverity.MINOR == "minor"
        assert IssueSeverity.SUGGESTION == "suggestion"


class TestRevisionSource:
    def test_values(self) -> None:
        assert RevisionSource.EDITOR_IN_CHIEF == "editor_in_chief"


def _make_issue(**overrides) -> ReviewIssue:
    defaults = {
        "severity": IssueSeverity.MAJOR,
        "dimension": ReviewDimension.METHODOLOGY,
        "description": "Method lacks integration protocol",
        "recommendation": "Add data integration matrix",
    }
    return ReviewIssue(**(defaults | overrides))


def _make_dimension(**overrides) -> EditorDimensionScore:
    defaults = {
        "dimension": ReviewDimension.METHODOLOGY,
        "score": 3.0,
        "weight": 0.25,
        "notes": "Adequate but could improve",
    }
    return EditorDimensionScore(**(defaults | overrides))


class TestReviewIssue:
    def test_valid_construction(self) -> None:
        issue = _make_issue()
        assert issue.severity == IssueSeverity.MAJOR
        assert issue.dimension == ReviewDimension.METHODOLOGY

    def test_frozen(self) -> None:
        issue = _make_issue()
        with pytest.raises(ValidationError):
            issue.severity = IssueSeverity.MINOR  # type: ignore[misc]

    def test_rejects_invalid_severity(self) -> None:
        with pytest.raises(ValidationError):
            _make_issue(severity="INVALID")

    def test_rejects_invalid_dimension(self) -> None:
        with pytest.raises(ValidationError):
            _make_issue(dimension="nonexistent")


class TestEditorDimensionScore:
    def test_valid_construction(self) -> None:
        ds = _make_dimension()
        assert ds.dimension == ReviewDimension.METHODOLOGY
        assert ds.score == 3.0

    def test_frozen(self) -> None:
        ds = _make_dimension()
        with pytest.raises(ValidationError):
            ds.score = 5.0  # type: ignore[misc]


class TestEditorReviewModel:
    def test_valid_construction(self) -> None:
        review = EditorReview(
            verdict=EditorialDecision.MAJOR_REVISION,
            weighted_score=2.8,
            dimensions=[_make_dimension()],
            issues=[_make_issue()],
            strengths=["Strong literature base"],
            summary="Needs methodology work.",
        )
        assert review.verdict == EditorialDecision.MAJOR_REVISION
        assert len(review.issues) == 1



class TestRevisionContext:
    def test_valid_construction(self) -> None:
        ctx = RevisionContext(
            round=1,
            source=RevisionSource.EDITOR_IN_CHIEF,
            target_node="ResearchArchitectNode",
            weakest_dimension=ReviewDimension.METHODOLOGY,
            feedback_summary="Methodology scored 2.1/5",
            issues=[_make_issue()],
            previous_output="Previous methodology blueprint text...",
        )
        assert ctx.round == 1
        assert ctx.source == RevisionSource.EDITOR_IN_CHIEF

    def test_rejects_invalid_source(self) -> None:
        with pytest.raises(ValidationError):
            RevisionContext(
                round=1,
                source="invalid_source",  # type: ignore[arg-type]
                target_node="ResearchArchitectNode",
                weakest_dimension=ReviewDimension.METHODOLOGY,
                feedback_summary="test",
                issues=[],
                previous_output="test",
            )

    def test_frozen(self) -> None:
        ctx = RevisionContext(
            round=1,
            source=RevisionSource.EDITOR_IN_CHIEF,
            target_node="ResearchArchitectNode",
            weakest_dimension=ReviewDimension.METHODOLOGY,
            feedback_summary="test",
            issues=[],
            previous_output="test",
        )
        with pytest.raises(ValidationError):
            ctx.round = 2  # type: ignore[misc]



# ---------------------------------------------------------------------------
# EvaluationResult model
# ---------------------------------------------------------------------------


def test_evaluation_result_model():
    result = EvaluationResult(
        verdict="PASS",
        scores={"relevance": 8.0, "coverage": 7.5},
        feedback="Good coverage overall.",
        weakest_dimension="coverage",
    )
    assert result.verdict == "PASS"
    assert result.scores["relevance"] == 8.0
    assert result.weakest_dimension == "coverage"
    # Frozen model
    with pytest.raises(ValidationError):
        result.verdict = "FAIL"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Compliance models (PRISMA-trAIce)
# ---------------------------------------------------------------------------


def test_compliance_item_result_model():
    from academic_pipeline.models.integrity import ComplianceItemResult

    item = ComplianceItemResult(
        item_id="M1",
        item_name="Protocol registration",
        tier="mandatory",
        verdict="fail",
        evidence="No protocol registration found in Methods.",
        reason="Missing pre-registration statement.",
    )
    assert item.item_id == "M1"
    assert item.tier == "mandatory"
    assert item.verdict == "fail"
    with pytest.raises(Exception):
        item.verdict = "pass"


def test_compliance_report_model():
    from academic_pipeline.models.integrity import (
        ComplianceItemResult,
        ComplianceReport,
    )

    report = ComplianceReport(
        stage="2.5",
        items=[
            ComplianceItemResult(
                item_id="M1", item_name="Protocol registration", tier="mandatory",
                verdict="pass", evidence="Protocol on OSF.", reason="Pre-registration stated.",
            )
        ],
        block_decision="pass",
        summary="All mandatory items pass.",
    )
    assert report.stage == "2.5"
    assert report.block_decision == "pass"
    assert len(report.items) == 1
    with pytest.raises(Exception):
        report.stage = "4.5"
