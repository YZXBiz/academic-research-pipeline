"""Tests for substitute_tokens (renderer-time ⟨num:label⟩ → \\hyperlink replacement)."""

from __future__ import annotations

import pytest

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.traceability.errors import SubstitutionFailure
from academic_pipeline.traceability.substitution import substitute_tokens


def _store(label: str, value: str) -> NumericalStore:
    return NumericalStore().add(NumericalProduct(
        label=label, value=value, unit=None, formula="f",
        source_run_id="r", source_step="s", source_artifact="a",
        source_code_line=None, context="c",
    ))


def test_substitute_emits_latex_hyperlink():
    store = _store("pct_a", "23.5")
    out = substitute_tokens("Value: ⟨num:pct_a⟩.", store, output_format="latex")
    assert out == r"Value: \hyperlink{num_pct_a}{23.5}."


def test_substitute_emits_plain_value_for_html():
    store = _store("pct_a", "23.5")
    out = substitute_tokens("Value: ⟨num:pct_a⟩.", store, output_format="html")
    assert out == "Value: 23.5."


def test_substitute_handles_multiple_tokens():
    store = _store("a", "1").add(NumericalProduct(
        label="b", value="2", unit=None, formula="f",
        source_run_id="r", source_step="s", source_artifact="a",
        source_code_line=None, context="c",
    ))
    out = substitute_tokens("⟨num:a⟩ and ⟨num:b⟩.", store, output_format="latex")
    assert out == r"\hyperlink{num_a}{1} and \hyperlink{num_b}{2}."


def test_substitute_unknown_label_raises_substitution_failure():
    store = _store("x", "1")
    with pytest.raises(SubstitutionFailure) as exc:
        substitute_tokens("⟨num:does_not_exist⟩.", store, output_format="latex")
    assert exc.value.label == "does_not_exist"


def test_substitute_no_tokens_passthrough():
    store = _store("x", "1")
    out = substitute_tokens("Plain prose with no tokens.", store, output_format="latex")
    assert out == "Plain prose with no tokens."
