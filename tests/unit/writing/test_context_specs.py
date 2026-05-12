"""Tests for per-agent ContextSpec instances (PRD §6.10.T2 + §6.10.T3).

DRAFT_WRITER_CONTEXT_SPEC was the first per-agent rollout (T2);
SECTION_WRITER_CONTEXT_SPEC adds the second writing-side spec under T3.
"""

from __future__ import annotations

from academic_pipeline.traceability.context_spec import ContextSpec
from academic_pipeline.writing.context_specs import (
    DRAFT_WRITER_CONTEXT_SPEC,
    SECTION_WRITER_CONTEXT_SPEC,
)


def test_draft_writer_spec_is_a_context_spec_instance() -> None:
    """DRAFT_WRITER_CONTEXT_SPEC must be an instance of the ContextSpec class
    (not a dict, not a custom subclass) — required by build_curated_context's
    strict isinstance check (PRD AP75).
    """
    assert isinstance(DRAFT_WRITER_CONTEXT_SPEC, ContextSpec)


def test_draft_writer_spec_lists_8_required_state_fields() -> None:
    """Per current DraftWriterNode invocation, draft_writer needs the same
    8 state fields the legacy build_context() call passed in."""
    expected = {
        "topic",
        "paper_outline",
        "argument_blueprint",
        "bibliography",
        "internal_review",
        "experiment_results",
        "experiment_analysis",
        "experiment_figures",
    }
    assert set(DRAFT_WRITER_CONTEXT_SPEC.allowed_products) == expected


def test_draft_writer_spec_grants_full_numerical_store_access() -> None:
    """Draft writer must be able to cite any value in the numerical_store
    via ⟨num:label⟩ tokens. 'all' = full store access (per ContextSpec
    Literal sentinel, distinct from [])."""
    assert DRAFT_WRITER_CONTEXT_SPEC.allowed_numerical_labels == "all"


def test_draft_writer_spec_is_frozen() -> None:
    """ContextSpec is frozen by design — instances must not mutate at
    runtime to keep agent context predictable across invocations."""
    import pydantic

    with (
        pydantic.ValidationError
        if False
        else __import__("pytest").raises(
            pydantic.ValidationError,
        )
    ):
        DRAFT_WRITER_CONTEXT_SPEC.allowed_products = ["something_else"]  # type: ignore[misc]


def test_draft_writer_node_uses_curated_context_with_the_spec() -> None:
    """DraftWriterNode.run must call build_curated_context(state, spec)
    with DRAFT_WRITER_CONTEXT_SPEC — not the legacy build_context list.

    We check by reading the source as a regression guard: the relevant
    line must reference DRAFT_WRITER_CONTEXT_SPEC and call
    build_curated_context. Source-level check is appropriate here because
    the alternative (mocking the agent + entire run_with_evaluation chain)
    pulls in the whole writing graph.
    """
    import inspect

    from academic_pipeline.writing import graph

    source = inspect.getsource(graph.DraftWriterNode)
    assert "DRAFT_WRITER_CONTEXT_SPEC" in source
    assert "build_curated_context" in source


def test_section_writer_spec_is_a_context_spec_instance() -> None:
    """T3 — SECTION_WRITER_CONTEXT_SPEC is a frozen ContextSpec instance."""
    assert isinstance(SECTION_WRITER_CONTEXT_SPEC, ContextSpec)


def test_section_writer_spec_lists_state_fields_section_writer_actually_reads() -> None:
    """The section writer reads experiment_results, experiment_analysis,
    experiment_figures, plus topic. The SectionSpec itself is a per-call
    argument — not from state."""
    expected = {"topic", "experiment_results", "experiment_analysis", "experiment_figures"}
    assert set(SECTION_WRITER_CONTEXT_SPEC.allowed_products) == expected


def test_section_writer_spec_grants_full_numerical_store_access() -> None:
    """Section writer cites figures and stats — needs full numerical_store."""
    assert SECTION_WRITER_CONTEXT_SPEC.allowed_numerical_labels == "all"


def test_section_writer_node_uses_curated_context_with_the_spec() -> None:
    """ParallelSectionWriterNode.run must reference SECTION_WRITER_CONTEXT_SPEC."""
    import inspect

    from academic_pipeline.writing import graph

    source = inspect.getsource(graph.ParallelSectionDraftNode)
    assert "SECTION_WRITER_CONTEXT_SPEC" in source
    assert "build_curated_context" in source
