"""Tests for the validate_tokens helper (PRD §6.10.T4).

`validate_tokens(text, store)` is a dry-run check that raises
SubstitutionFailure (TRC003) on any unresolved ⟨num:label⟩ token,
without performing the actual substitution. Used by the editorial
gate to fail-fast at decision time rather than blowing up at LaTeX
compile time.
"""

from __future__ import annotations

import pytest

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.traceability.errors import SubstitutionFailure
from academic_pipeline.traceability.substitution import validate_tokens


def _store(label: str, value: str) -> NumericalStore:
    return NumericalStore().add(
        NumericalProduct(
            label=label,
            value=value,
            unit=None,
            formula="f",
            source_run_id="r",
            source_step="s",
            source_artifact="a",
            source_code_line=None,
            context="c",
        )
    )


def test_validate_tokens_passes_when_all_resolve() -> None:
    store = _store("pct_a", "23.5")
    # No exception raised
    validate_tokens("Value: ⟨num:pct_a⟩.", store)


def test_validate_tokens_passes_when_no_tokens_present() -> None:
    store = NumericalStore()
    validate_tokens("Plain prose with no tokens.", store)


def test_validate_tokens_raises_substitution_failure_on_unresolved() -> None:
    store = _store("known", "1")
    with pytest.raises(SubstitutionFailure) as exc:
        validate_tokens("Cite ⟨num:does_not_exist⟩ here.", store)
    assert exc.value.label == "does_not_exist"


def test_validate_tokens_raises_on_first_unresolved_when_multiple() -> None:
    store = NumericalStore()
    with pytest.raises(SubstitutionFailure) as exc:
        validate_tokens("⟨num:first⟩ then ⟨num:second⟩.", store)
    # First in document order is the one reported
    assert exc.value.label == "first"


def test_validate_tokens_does_not_modify_text() -> None:
    """validate_tokens is a dry-run check — it must not perform substitution."""
    store = _store("x", "99")
    text = "Value: ⟨num:x⟩."
    # If validate_tokens accidentally returned substituted text we'd be
    # tempted to use it; the function returns None to make that impossible.
    result = validate_tokens(text, store)
    assert result is None


def test_validate_tokens_threads_section_name_into_error() -> None:
    store = NumericalStore()
    with pytest.raises(SubstitutionFailure) as exc:
        validate_tokens("⟨num:miss⟩", store, section_name="results")
    assert exc.value.section_name == "results"
