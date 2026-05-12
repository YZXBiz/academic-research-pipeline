"""Tests for generate_notes_appendix LaTeX renderer."""

from __future__ import annotations

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.traceability.notes_appendix import generate_notes_appendix


def _store_with_two_products() -> NumericalStore:
    s = NumericalStore()
    s = s.add(NumericalProduct(
        label="pct_a", value="23.5", unit="%", formula="100 * mean(x > 8)",
        source_run_id="run-x", source_step="experiment", source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:42", context="Prevalence among elderly diabetics",
    ))
    s = s.add(NumericalProduct(
        label="auc", value="0.87", unit=None, formula="roc_auc_score(y, p)",
        source_run_id="run-x", source_step="experiment", source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:67", context="Test-set AUC for primary model",
    ))
    return s


def test_appendix_contains_section_header():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels={"pct_a", "auc"})
    assert r"\section{Calculation Notes}" in out


def test_appendix_emits_hypertarget_per_cited_label():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels={"pct_a", "auc"})
    assert r"\hypertarget{num_pct_a}" in out
    assert r"\hypertarget{num_auc}" in out


def test_appendix_includes_value_unit_formula_context():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels={"pct_a"})
    assert "23.5" in out
    assert "%" in out
    assert "100 * mean(x > 8)" in out
    assert "Prevalence among elderly diabetics" in out


def test_appendix_includes_code_line_link_when_source_code_line_present():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels={"pct_a"})
    # Hyperlink to the code-appendix anchor for the source line
    assert r"\hyperlink{code_run-x_42}" in out
    assert "analysis.py:42" in out


def test_appendix_skips_uncited_labels():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels={"pct_a"})
    assert "pct_a" in out
    # auc is not cited, should not appear in the appendix
    assert "num_auc" not in out


def test_appendix_empty_when_no_cited_labels():
    out = generate_notes_appendix(_store_with_two_products(), cited_labels=set())
    assert out == ""
