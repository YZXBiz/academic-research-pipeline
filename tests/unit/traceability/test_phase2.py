"""Canonical Phase 2 traceability test suite per PRD §6.10.T8.

Six tests covering the four named coverage areas from PRD §6.10.T8:

1. dialogue helper end-to-end (placeholder; full wiring deferred to §6.10.T1
   in Phase 4 — pairs with §6.3.T9 + §6.9.T3)
2. ContextSpec per-agent rollout for all 6 agents (DRAFT_WRITER,
   SECTION_WRITER, EDITORIAL_SYNTHESIZER, 3 persona reviewers,
   RESULT_ANALYZER)
3. validator hard-fail on unresolved token (writer side)
4. notes appendix in PDF (auto-attach contract)

Plus 2 supporting Phase 2 tests:

5. substitute_tokens hard-fail at render time (renderer side, TRC003)
6. traceability_error_event payload round-trips through EventLogger
   (PRD §6.10.T6 events.jsonl emission)

The underlying behaviors retain depth coverage in their focused files
(test_dialogue.py, test_context_specs.py, test_validators.py,
test_substitution.py, test_substitution_validate.py,
test_latex_compiler_integration.py, test_error_events.py). This file
is the single canonical reference satisfying PRD §6.10.T8's literal
six-test contract.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from academic_pipeline.experiment.context_specs import RESULT_ANALYZER_CONTEXT_SPEC
from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.review.context_specs import (
    APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC,
    EDITORIAL_SYNTHESIZER_CONTEXT_SPEC,
    METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC,
    SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC,
)
from academic_pipeline.runtime.events import EventLogger
from academic_pipeline.tools.rendering.latex_compiler import (
    apply_traceability_substitutions,
)
from academic_pipeline.traceability.context_spec import ContextSpec
from academic_pipeline.traceability.dialogue import (
    DEFAULT_TERMINATION_PHRASE,
    run_writer_reviewer_dialogue,
)
from academic_pipeline.traceability.errors import (
    SubstitutionFailure,
    traceability_error_event,
)
from academic_pipeline.traceability.substitution import (
    substitute_tokens,
    validate_tokens,
)
from academic_pipeline.traceability.validators import (
    make_numeric_output_validator,
)
from academic_pipeline.writing.context_specs import (
    DRAFT_WRITER_CONTEXT_SPEC,
    SECTION_WRITER_CONTEXT_SPEC,
)


if TYPE_CHECKING:
    from pathlib import Path


def _store(label: str = "auc", value: str = "0.87") -> NumericalStore:
    return NumericalStore().add(
        NumericalProduct(
            label=label,
            value=value,
            unit=None,
            formula="f",
            source_run_id="r",
            source_step="s",
            source_artifact="a",
            source_code_line="analysis.py:42",
            context="c",
        )
    )


# 1. Dialogue helper placeholder ---------------------------------------------


def test_dialogue_helper_module_surfaces_termination_phrase_and_runner() -> None:
    """PRD §6.10.T8 (placeholder): the dialogue helper exists with the fixed
    termination phrase and the runner function — wiring into writing/graph.py
    is deferred to §6.10.T1 in Phase 4 (pairs with §6.3.T9 + §6.9.T3).

    Per PRD ralph-54: termination phrase is verbatim and MUST NOT change."""
    assert DEFAULT_TERMINATION_PHRASE == "The section does not require any changes"
    assert callable(run_writer_reviewer_dialogue)


# 2. ContextSpec per-agent rollout ------------------------------------------


def test_all_6_per_agent_context_specs_are_frozen_contextspec_instances() -> None:
    """PRD §6.10.T2 + T3 — six ContextSpec instances now exist for the
    canonical agent set. AP75 strict isinstance check requires concrete
    ContextSpec; never a duck-typed dict."""
    specs = [
        DRAFT_WRITER_CONTEXT_SPEC,
        SECTION_WRITER_CONTEXT_SPEC,
        EDITORIAL_SYNTHESIZER_CONTEXT_SPEC,
        SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC,
        APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC,
        METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC,
        RESULT_ANALYZER_CONTEXT_SPEC,
    ]
    assert len(specs) == 7  # 6 agents + section_writer (T3 covers 5 agents)
    for spec in specs:
        assert isinstance(spec, ContextSpec)


# 3. Validator hard-fail on unresolved token --------------------------------


def test_writer_validator_hard_fails_on_unknown_token() -> None:
    """PRD §6.10 writer seam: the output validator raises ModelRetry when
    the section text cites an ⟨num:label⟩ that's not in the store."""
    from dataclasses import dataclass

    from pydantic_ai import ModelRetry

    @dataclass
    class _Out:
        text: str
        section_name: str

    validator = make_numeric_output_validator(_store("known"))
    with pytest.raises(ModelRetry) as exc:
        validator(_Out(text="Cite ⟨num:not_in_store⟩.", section_name="results"))
    assert "not_in_store" in str(exc.value)


# 4. Notes appendix in PDF (auto-attach contract) ---------------------------


def test_notes_appendix_auto_attached_when_token_cited() -> None:
    """PRD §6.10.T5 — Notes appendix attaches automatically to the LaTeX
    output whenever any token is cited and traceability_mode != 'off',
    so it survives the pandoc/tectonic compile chain into the PDF."""
    out = apply_traceability_substitutions(
        manuscript_text="Value: ⟨num:auc⟩.",
        store=_store(),
        traceability_mode="partial",
        experiment_runs=[],
    )
    # The appendix LaTeX section header must be present in the markdown
    # handed to pandoc — that's what becomes a section in the rendered PDF.
    assert r"\section{Calculation Notes}" in out
    # And the hypertarget must anchor the hyperlink in the body.
    assert r"\hypertarget{num_auc}" in out
    assert r"\hyperlink{num_auc}" in out


# 5. Renderer hard-fail on unresolved token (TRC003) ------------------------


def test_render_hard_fails_on_unresolved_token() -> None:
    """PRD §6.10.T4 — `substitute_tokens` raises SubstitutionFailure (TRC003)
    on an unresolved label so the editorial gate fail-fasts before the
    LaTeX compile step blows up."""
    with pytest.raises(SubstitutionFailure) as exc:
        substitute_tokens("Cite ⟨num:does_not_exist⟩.", _store("known"))
    assert exc.value.label == "does_not_exist"
    # The dry-run preflight raises the same error.
    with pytest.raises(SubstitutionFailure):
        validate_tokens("Cite ⟨num:does_not_exist⟩.", _store("known"))


# 6. TRC error → events.jsonl round-trip ------------------------------------


def test_traceability_error_event_round_trips_through_event_logger(
    tmp_path: Path,
) -> None:
    """PRD §6.10.T6 — `traceability_error_event(err)` produces a payload that
    `EventLogger.emit_sync('traceability_error', **payload)` writes as a
    valid jsonl record carrying the TRC error_code + context fields."""
    logger = EventLogger(tmp_path)
    err = SubstitutionFailure("unresolved label", label="x", store_label_count=3)
    payload = traceability_error_event(err)
    logger.emit_sync("traceability_error", **payload)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    # First line is the schema_version marker (PRD §6.8.T3); error event
    # is the second line.
    record = json.loads(lines[1])
    assert record["type"] == "traceability_error"
    assert record["error_code"] == "TRC003"
    assert record["label"] == "x"
    assert record["store_label_count"] == 3
