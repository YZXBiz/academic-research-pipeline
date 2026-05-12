"""Unit tests for build_context revision injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from academic_pipeline.models.review import (
    ReviewIssue,
    RevisionContext,
)
from academic_pipeline.core.enums import IssueSeverity, ReviewDimension, RevisionSource
from academic_pipeline.runtime.context import build_context


@dataclass
class _FakeState:
    topic: str = "AI in education"
    rq_brief: dict[str, Any] = field(default_factory=lambda: {"raw": "Some RQ"})
    revision_context: RevisionContext | None = None


def _make_revision_context(target_node: str = "ResearchArchitectNode") -> RevisionContext:
    return RevisionContext(
        round=1,
        source=RevisionSource.EDITOR_IN_CHIEF,
        target_node=target_node,
        weakest_dimension=ReviewDimension.METHODOLOGY,
        feedback_summary="Methodology scored 2.1/5",
        issues=[
            ReviewIssue(
                severity=IssueSeverity.CRITICAL,
                dimension=ReviewDimension.METHODOLOGY,
                description="No integration protocol",
                recommendation="Add data integration matrix",
            ),
        ],
        previous_output="Previous methodology blueprint...",
    )


class TestBuildContextRevision:
    def test_no_revision_context_unchanged(self) -> None:
        state = _FakeState()
        result = build_context(state, ["topic"])
        assert "REVISION INSTRUCTIONS" not in result
        assert "AI in education" in result

    def test_revision_context_no_node_name_unchanged(self) -> None:
        state = _FakeState(revision_context=_make_revision_context())
        result = build_context(state, ["topic"])
        assert "REVISION INSTRUCTIONS" not in result

    def test_revision_context_wrong_node_unchanged(self) -> None:
        state = _FakeState(revision_context=_make_revision_context())
        result = build_context(state, ["topic"], node_name="BibliographyNode")
        assert "REVISION INSTRUCTIONS" not in result

    def test_revision_context_matching_node_injects(self) -> None:
        state = _FakeState(revision_context=_make_revision_context())
        result = build_context(state, ["topic"], node_name="ResearchArchitectNode")
        assert "REVISION INSTRUCTIONS" in result
        assert "Methodology scored 2.1/5" in result
        assert "No integration protocol" in result
        assert "Previous methodology blueprint..." in result

    def test_revision_context_cleared_after_consumption(self) -> None:
        state = _FakeState(revision_context=_make_revision_context())
        build_context(state, ["topic"], node_name="ResearchArchitectNode")
        assert state.revision_context is None

