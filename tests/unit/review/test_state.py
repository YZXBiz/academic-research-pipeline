"""Tests for ReviewState dataclass."""

from __future__ import annotations

from academic_pipeline.models.shared import (
    Author,
    Reference,
)
from academic_pipeline.models.writing import (
    PaperDraft,
    Section,
)
from academic_pipeline.models.review import (
    ResponseItem,
    ResponseToReviewers,
    RevisionRoadmap,
)
from academic_pipeline.review.state import ReviewState
from academic_pipeline.core.enums import EditorialDecision


def _make_paper_draft() -> PaperDraft:
    return PaperDraft(
        title="Test",
        abstract="Abstract",
        authors=[Author(name="Smith", affiliation="MIT")],
        keywords=["a", "b", "c"],
        sections=[Section(heading="Intro", level=1, content="Draft content here", word_count=50, citation_count=1)],
        references=[Reference(id="r1", full_citation="Smith (2024)")],
        total_word_count=50,
    )


def _make_revision_roadmap() -> RevisionRoadmap:
    return RevisionRoadmap(
        items=[],
        total_items=0,
        must_fix_count=0,
        editorial_decision="Major Revision",
        consensus_summary="Reviewers agree on major revision",
    )


def _make_response_to_reviewers() -> ResponseToReviewers:
    return ResponseToReviewers(
        revision_round=1,
        items=[
            ResponseItem(
                roadmap_item_id="item1",
                reviewer_comment="Fix methodology",
                author_response="Fixed",
                change_location="Section 3",
                status="RESOLVED",
            )
        ],
    )


class TestReviewState:
    def test_default_construction(self) -> None:
        state = ReviewState()
        assert state.paper_draft is None
        assert state.review_report == {}
        assert state.revision_roadmap == {}
        assert state.response_to_reviewers is None
        assert state.messages == []
        assert state.reviewer_reports == []
        assert state.current_reviewer_id == ""
        assert state.current_reviewer_agent == ""
        assert state.editorial_decision is None
        assert state.needs_coaching is False

    def test_editorial_decision_accepts_enum(self) -> None:
        state = ReviewState(editorial_decision=EditorialDecision.ACCEPT)
        assert state.editorial_decision == EditorialDecision.ACCEPT

    def test_editorial_decision_minor_revision(self) -> None:
        state = ReviewState(editorial_decision=EditorialDecision.MINOR_REVISION)
        assert state.editorial_decision == EditorialDecision.MINOR_REVISION

    def test_editorial_decision_major_revision(self) -> None:
        state = ReviewState(editorial_decision=EditorialDecision.MAJOR_REVISION)
        assert state.editorial_decision == EditorialDecision.MAJOR_REVISION

    def test_editorial_decision_reject(self) -> None:
        state = ReviewState(editorial_decision=EditorialDecision.REJECT)
        assert state.editorial_decision == EditorialDecision.REJECT

    def test_messages_independent(self) -> None:
        s1 = ReviewState()
        s2 = ReviewState()
        s1.messages.append({"role": "user", "content": "hi"})
        assert s2.messages == []

    def test_mutable_defaults_independent(self) -> None:
        """Verify dict/list defaults use default_factory (no shared state).

        Typed model fields (paper_draft, revision_roadmap, response_to_reviewers)
        default to None and are immutable frozen models, so they are excluded.
        """
        s1 = ReviewState()
        s2 = ReviewState()
        s1.review_report["score"] = 8
        s1.reviewer_reports.append({"reviewer": "R1", "score": 7})
        assert s2.review_report == {}
        assert s2.reviewer_reports == []

    def test_construction_with_all_fields(self) -> None:
        draft = _make_paper_draft()
        rtr = _make_response_to_reviewers()
        state = ReviewState(
            paper_draft=draft,
            review_report={"overall": "major revision"},
            revision_roadmap={"items": [], "total_items": 0},
            response_to_reviewers=rtr,
            messages=[{"role": "system", "content": "init"}],
            reviewer_reports=[{"reviewer": "R1", "recommendation": "major"}],
            current_reviewer_id="reviewer_1",
            current_reviewer_agent="methodology_reviewer",
            editorial_decision=EditorialDecision.MAJOR_REVISION,
            needs_coaching=True,
        )
        assert state.paper_draft is not None
        assert state.paper_draft.title == "Test"
        assert state.review_report["overall"] == "major revision"
        assert state.current_reviewer_id == "reviewer_1"
        assert state.current_reviewer_agent == "methodology_reviewer"
        assert state.editorial_decision == EditorialDecision.MAJOR_REVISION
        assert state.needs_coaching is True
        assert len(state.reviewer_reports) == 1
