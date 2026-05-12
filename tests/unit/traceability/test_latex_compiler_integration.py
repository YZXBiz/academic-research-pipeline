"""Tests for substitution + Notes appendix wiring in the latex compiler.

These don't invoke pandoc — they verify that the wiring layer correctly
substitutes tokens, generates the Notes appendix, and concatenates them
in the right order before pandoc would be called.
"""

from __future__ import annotations

from dataclasses import dataclass

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.tools.rendering.latex_compiler import (
    apply_traceability_substitutions,
)
from academic_pipeline.traceability.notes_appendix import generate_notes_appendix
from academic_pipeline.traceability.substitution import substitute_tokens


def _store_with_one_product() -> NumericalStore:
    return NumericalStore().add(
        NumericalProduct(
            label="pct_a",
            value="23.5",
            unit="%",
            formula="100*mean(x>8)",
            source_run_id="r",
            source_step="s",
            source_artifact="a",
            source_code_line="analysis.py:42",
            context="Prevalence",
        )
    )


def test_substitute_then_appendix_round_trip() -> None:
    store = _store_with_one_product()
    manuscript = "The rate is ⟨num:pct_a⟩."
    substituted = substitute_tokens(manuscript, store, output_format="latex")
    appendix = generate_notes_appendix(store, cited_labels={"pct_a"})

    # Hyperlink in manuscript matches hypertarget in appendix
    assert r"\hyperlink{num_pct_a}{23.5}" in substituted
    assert r"\hypertarget{num_pct_a}" in appendix


def test_traceability_renderer_helper_returns_unchanged_text_when_mode_off() -> None:
    """The wiring in latex_compiler.py MUST be a no-op when traceability_mode=='off'.

    This test just documents the contract; the actual no-op happens at the call
    site via an `if config.traceability_mode != 'off':` guard.
    """
    store = _store_with_one_product()
    out = apply_traceability_substitutions(
        manuscript_text="The rate is ⟨num:pct_a⟩.",
        store=store,
        traceability_mode="off",
        experiment_runs=[],
    )
    # Off mode: tokens NOT substituted, no appendix appended
    assert out == "The rate is ⟨num:pct_a⟩."


def test_traceability_renderer_helper_substitutes_and_appends_when_partial() -> None:
    store = _store_with_one_product()
    out = apply_traceability_substitutions(
        manuscript_text="The rate is ⟨num:pct_a⟩.",
        store=store,
        traceability_mode="partial",
        experiment_runs=[],
    )
    assert r"\hyperlink{num_pct_a}{23.5}" in out
    assert r"\section{Calculation Notes}" in out


def test_notes_appendix_auto_attaches_without_caller_opting_in() -> None:
    """PRD §6.10.T5 — Notes appendix attaches automatically when ANY token is
    cited and traceability_mode != 'off'. Callers must not have to pass an extra
    flag or call generate_notes_appendix separately — the wiring in
    apply_traceability_substitutions handles it.
    """
    store = _store_with_one_product()
    out = apply_traceability_substitutions(
        manuscript_text="Cite ⟨num:pct_a⟩ and stop.",
        store=store,
        traceability_mode="partial",
        experiment_runs=[],
    )
    # The auto-attach contract: a Calculation Notes section appears
    # immediately after the substituted manuscript body.
    assert r"\section{Calculation Notes}" in out
    # The hypertarget anchoring the hyperlink in the manuscript MUST appear in
    # the appended appendix — proves the appendix was generated against the
    # SAME store that the substitution used.
    assert r"\hypertarget{num_pct_a}" in out
    # And the appendix appears AFTER the substituted text (auto-attach order).
    assert out.index(r"\hyperlink{num_pct_a}") < out.index(r"\section{Calculation Notes}")


def test_notes_appendix_omitted_when_no_tokens_cited() -> None:
    """When the manuscript cites zero tokens, the auto-attach must skip the
    appendix entirely — empty itemize would crash tectonic."""
    store = _store_with_one_product()
    out = apply_traceability_substitutions(
        manuscript_text="Plain prose, no citations.",
        store=store,
        traceability_mode="partial",
        experiment_runs=[],
    )
    assert r"\section{Calculation Notes}" not in out
    assert out == "Plain prose, no citations."


def test_traceability_renderer_helper_includes_code_appendix_when_full() -> None:
    """Full mode appends Code appendix in addition to Notes appendix."""

    @dataclass(frozen=True)
    class _Run:
        run_id: str
        code: str
        code_filename: str
        producing_lines: tuple[int, ...]

    store = _store_with_one_product()
    out = apply_traceability_substitutions(
        manuscript_text="The rate is ⟨num:pct_a⟩.",
        store=store,
        traceability_mode="full",
        experiment_runs=[_Run(run_id="r", code="x = 1\ny = 2\n", code_filename="a.py", producing_lines=(1,))],
    )
    assert r"\section{Code: a.py}" in out
    assert r"\hypertarget{code_r_1}" in out
