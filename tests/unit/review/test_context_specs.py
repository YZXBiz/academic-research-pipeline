"""Tests for review-subgraph per-agent ContextSpec instances (PRD §6.10.T3).

Covers EDITORIAL_SYNTHESIZER_CONTEXT_SPEC + the 3 persona-anchored
reviewer specs (PRD AP75 strict isinstance check).
"""

from __future__ import annotations

from academic_pipeline.review.context_specs import (
    APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC,
    EDITORIAL_SYNTHESIZER_CONTEXT_SPEC,
    METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC,
    SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC,
)
from academic_pipeline.traceability.context_spec import ContextSpec


def test_editorial_synthesizer_spec_is_a_context_spec() -> None:
    assert isinstance(EDITORIAL_SYNTHESIZER_CONTEXT_SPEC, ContextSpec)


def test_editorial_synthesizer_spec_lists_paper_draft_and_reviewer_reports() -> None:
    """Editorial synthesizer reads paper_draft + reviewer_reports and may
    optionally read cascade_result. allowed_products lists all three so the
    optional cascade-aware path stays curated when cascaded_review_enabled."""
    expected = {"paper_draft", "reviewer_reports", "cascade_result"}
    assert set(EDITORIAL_SYNTHESIZER_CONTEXT_SPEC.allowed_products) == expected


def test_editorial_synthesizer_does_not_cite_numerical_values() -> None:
    """Editorial synthesizer judges and decides — it does not cite stats.
    Empty list = no numerical citations allowed (distinct from 'all')."""
    assert EDITORIAL_SYNTHESIZER_CONTEXT_SPEC.allowed_numerical_labels == []


def test_three_persona_reviewer_specs_each_only_read_paper_draft() -> None:
    """The 3 persona reviewers (senior_gatekeeper, applied_practitioner,
    methodology_purist) each read only paper_draft per the actual call
    site (review/graph.py:_run_persona_reviewer)."""
    for spec in (
        SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC,
        APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC,
        METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC,
    ):
        assert isinstance(spec, ContextSpec)
        assert spec.allowed_products == ["paper_draft"]
        assert spec.allowed_numerical_labels == []


def test_editorial_synthesizer_node_uses_curated_context_with_the_spec() -> None:
    """EditorialSynthesizerNode.run must reference EDITORIAL_SYNTHESIZER_CONTEXT_SPEC."""
    import inspect

    from academic_pipeline.review import graph

    source = inspect.getsource(graph.EditorialSynthesizerNode)
    assert "EDITORIAL_SYNTHESIZER_CONTEXT_SPEC" in source
    assert "build_curated_context" in source


def test_persona_reviewer_dispatch_uses_curated_context() -> None:
    """ParallelReviewerNode._run_persona_reviewer must reference one of the
    persona ContextSpec instances + build_curated_context."""
    import inspect

    from academic_pipeline.review import graph

    source = inspect.getsource(graph.ParallelReviewerNode)
    assert "build_curated_context" in source
    # at least one of the 3 persona spec names must appear
    assert "PERSONA_REVIEWER_SPECS" in source or any(
        name in source
        for name in (
            "SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC",
            "APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC",
            "METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC",
        )
    )
