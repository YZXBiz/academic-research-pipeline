"""Tests for editorial gate hard-fail on unresolved trace tokens (PRD §6.10.T4).

The editorial gate must reject (raise TRC003 SubstitutionFailure) when the
paper_draft contains ⟨num:label⟩ tokens that don't resolve in the
numerical_store. Catching unresolved tokens at editorial time surfaces the
problem before LaTeX compile and stops a stale draft from leaving the
editorial gate.
"""

from __future__ import annotations

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.traceability.errors import SubstitutionFailure
from academic_pipeline.traceability.substitution import find_unresolved_tokens


def _store(*labels: str) -> NumericalStore:
    s = NumericalStore()
    for label in labels:
        s = s.add(
            NumericalProduct(
                label=label,
                value="1",
                unit=None,
                formula="f",
                source_run_id="r",
                source_step="s",
                source_artifact="a",
                source_code_line=None,
                context="c",
            ),
        )
    return s


def test_find_unresolved_tokens_returns_labels_not_in_store() -> None:
    store = _store("known_a", "known_b")
    text = "We saw ⟨num:known_a⟩ and ⟨num:missing_x⟩ and ⟨num:also_missing⟩."
    assert find_unresolved_tokens(text, store) == ["missing_x", "also_missing"]


def test_find_unresolved_tokens_empty_when_all_resolve() -> None:
    store = _store("a", "b")
    text = "⟨num:a⟩ and ⟨num:b⟩ resolve fine."
    assert find_unresolved_tokens(text, store) == []


def test_find_unresolved_tokens_handles_text_with_no_tokens() -> None:
    store = _store("a")
    assert find_unresolved_tokens("Plain prose, no tokens.", store) == []


def test_find_unresolved_tokens_preserves_first_occurrence_order() -> None:
    """Order matters for error messages — caller should see the FIRST
    unresolved token in the section for easier authoring fix-up."""
    store = _store()
    text = "⟨num:second_seen⟩ and ⟨num:first_seen⟩ wait — ⟨num:first_seen⟩ again."
    # Each unique label appears once in the result, in first-occurrence order.
    assert find_unresolved_tokens(text, store) == ["second_seen", "first_seen"]


def test_substitution_failure_carries_label_for_first_unresolved() -> None:
    """Existing substitute_tokens still raises on first unresolved — the
    new helper does NOT replace it."""
    import pytest

    from academic_pipeline.traceability.substitution import substitute_tokens

    store = _store("a")
    with pytest.raises(SubstitutionFailure) as exc:
        substitute_tokens("⟨num:a⟩ and ⟨num:bogus⟩", store, output_format="latex")
    assert exc.value.label == "bogus"


def test_formatter_node_wiring_uses_find_unresolved_tokens() -> None:
    """FormatterNode.run must call find_unresolved_tokens on the paper_draft
    sections + numerical_store as a preflight to LaTeX compile (PRD §6.10.T4)."""
    import inspect

    from academic_pipeline.writing import graph

    source = inspect.getsource(graph.FormatterNode)
    assert "find_unresolved_tokens" in source
    assert "SubstitutionFailure" in source
    assert "TRC003" in source
