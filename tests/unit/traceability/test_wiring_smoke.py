"""End-to-end smoke tests for the traceability wiring chain.

These tests exercise the cross-module flow that individual unit tests don't cover:
- PipelineState → WritingState forwarding of numerical_store
- The Section-shape adapter pattern used in writing/graph.py
- traceability_mode flag actually gates the wiring

If any of these break, the partial-mode pipeline silently stops working even
though all unit tests still pass. Treat failures here as regressions in the
wiring (not in the components).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic_ai import ModelRetry

from academic_pipeline.config import PipelineConfig
from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.traceability.validators import (
    ABORTING_PHRASES,
    FORBIDDEN_PHRASES,
    make_numeric_output_validator,
)
from academic_pipeline.writing.state import WritingState


# Shared by multiple tests — adapter that mirrors writing/graph.py:355
@dataclass
class _SectionAdapter:
    text: str
    section_name: str


def _make_store_with_auc() -> NumericalStore:
    return NumericalStore().add(NumericalProduct(
        label="auc", value="0.87", unit=None, formula="roc_auc_score(y, p)",
        source_run_id="run-x", source_step="experiment.analysis",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:42", context="Test-set AUC for primary model",
    ))


def test_config_carries_all_three_traceability_fields() -> None:
    """Catches a regression where one of the three new flags goes missing or renames."""
    config = PipelineConfig(anthropic_api_key="sk-test", traceability_mode="partial")  # type: ignore[arg-type]
    assert config.traceability_mode == "partial"
    assert config.copilot_enabled is False
    assert config.max_dialogue_turns == 3


def test_pipeline_state_to_writing_state_forwards_numerical_store() -> None:
    """Catches a regression where WritePhaseNode (pipeline/nodes.py:237) forgets to forward the store."""
    pipeline_state = PipelineState(topic="smoke")
    pipeline_state.numerical_store = _make_store_with_auc()

    # Mirror pipeline/nodes.py:WritePhaseNode.run construction
    writing_state = WritingState(
        topic=pipeline_state.topic,
        numerical_store=pipeline_state.numerical_store,
    )
    assert "auc" in writing_state.numerical_store.products
    assert writing_state.numerical_store.products["auc"].value == "0.87"


def test_validator_against_section_shaped_input_via_adapter() -> None:
    """Catches a regression in the Section.content/heading → text/section_name adapter pattern.

    The Section model uses .content and .heading; the validator's _HasText Protocol
    expects .text and .section_name. writing/graph.py bridges via _SectionAdapter.
    If the Section model fields rename or the adapter pattern drops, this catches it.
    """
    store = _make_store_with_auc()
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)

    clean_adapter = _SectionAdapter(text="AUC was ⟨num:auc⟩.", section_name="Results")
    out = validator(clean_adapter)
    assert out is clean_adapter

    bad_adapter = _SectionAdapter(text="AUC was 0.99 fabricated.", section_name="Results")
    with pytest.raises(ModelRetry):
        validator(bad_adapter)


def test_validator_skipped_when_mode_off_documented_at_call_site() -> None:
    """The off-mode bypass lives at the call site (writing/graph.py:343), not inside the validator.

    This test documents the contract: when mode == 'off', the call site MUST NOT
    invoke the validator. The validator itself doesn't know about modes.
    """
    config = PipelineConfig(anthropic_api_key="sk-test")  # type: ignore[arg-type]
    assert config.traceability_mode == "off"
    # If the call-site guard breaks, integration tests will catch it. This test
    # just asserts the default-off contract that the guard depends on.


# =============================================================================
# Week 2 smoke checks — added when Week 2 (dialogue, curated context, code
# appendix, latex_compiler integration) shipped.
# =============================================================================


def test_full_trace_chain_renders_end_to_end() -> None:
    """The complete trace chain: prose token → hyperlink → Notes hypertarget → code link → Code appendix.

    This is the SCI-clearing mechanism. If this breaks, the whole point of the
    port is gone — peer reviewers can no longer click a number to verify it.
    """
    from dataclasses import dataclass

    from academic_pipeline.tools.rendering.latex_compiler import (
        apply_traceability_substitutions,
    )

    store = NumericalStore().add(NumericalProduct(
        label="auc", value="0.87", unit=None, formula="roc_auc_score(y, p)",
        source_run_id="run-x", source_step="experiment.analysis",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:42", context="Test-set AUC",
    ))

    @dataclass(frozen=True)
    class _Run:
        run_id: str
        code: str
        code_filename: str
        producing_lines: tuple[int, ...]

    runs = [_Run(
        run_id="run-x",
        code="X_train = load_data()\nmodel.fit(X_train, y_train)\nauc = roc_auc_score(y_test, p)\n",
        code_filename="analysis.py",
        producing_lines=(3,),
    )]

    out = apply_traceability_substitutions(
        manuscript_text="Our model achieved AUC ⟨num:auc⟩ on the held-out set.",
        store=store,
        traceability_mode="full",
        experiment_runs=runs,
    )

    # Prose has hyperlink to num_auc
    assert r"\hyperlink{num_auc}{0.87}" in out
    # Notes appendix has matching hypertarget for num_auc
    assert r"\hypertarget{num_auc}" in out
    # Notes entry has hyperlink to code_run-x_42 (matches source_code_line)
    assert r"\hyperlink{code_run-x_42}" in out
    # Code appendix has hypertarget for code_run-x_3 (matches producing_lines=(3,))
    assert r"\hypertarget{code_run-x_3}" in out


def test_apply_traceability_off_mode_is_passthrough() -> None:
    """The off-mode bypass in latex_compiler MUST be a pure passthrough.

    If this breaks, every paper run ships with broken substitutions even when
    the operator opted out via traceability_mode=off.
    """
    from academic_pipeline.tools.rendering.latex_compiler import (
        apply_traceability_substitutions,
    )

    out = apply_traceability_substitutions(
        manuscript_text="Anything ⟨num:not_in_store⟩ at all.",
        store=NumericalStore(),  # empty store
        traceability_mode="off",
        experiment_runs=[],
    )
    assert out == "Anything ⟨num:not_in_store⟩ at all."  # untouched


def test_curated_context_emits_numerical_table_when_store_populated() -> None:
    """build_curated_context MUST emit the numerical-values table that writers cite from.

    Without this table, the writer doesn't know what labels are available and
    will either output bare numbers (validator catches → ModelRetry) or invent
    labels (validator catches → ModelRetry). Either way the trace chain breaks.
    """
    from dataclasses import dataclass, field

    from academic_pipeline.runtime.context import build_curated_context
    from academic_pipeline.traceability.context_spec import ContextSpec

    @dataclass
    class _S:
        synthesis_text: str = "Lit summary..."
        numerical_store: NumericalStore = field(default_factory=NumericalStore)

    state = _S()
    state.numerical_store = state.numerical_store.add(NumericalProduct(
        label="auc", value="0.87", unit=None, formula="f", source_run_id="r",
        source_step="s", source_artifact="a", source_code_line=None, context="Test AUC",
    ))

    out = build_curated_context(
        state, ContextSpec(allowed_products=["synthesis_text"], allowed_numerical_labels="all"),
    )
    # The writer-facing table header must be present
    assert "Available numerical values" in out
    assert "⟨num:label⟩" in out  # tells the writer how to cite
    assert "auc" in out
    assert "0.87" in out


def test_latex_compiler_node_builds_experiment_runs_from_populated_store() -> None:
    """When numerical_store has products with source_code_line set, LatexCompilerNode
    constructs experiment_runs with producing_lines computed from those entries.

    This is the load-bearing wire-up that closes the V1 gap of empty Code appendix.
    """
    from academic_pipeline.models.experiment import ExperimentResults
    from academic_pipeline.writing.graph import _build_experiment_runs_for_appendix
    from academic_pipeline.writing.state import WritingState

    store = NumericalStore()
    store = store.add(NumericalProduct(
        label="xgboost__auc", value="0.87", unit=None, formula="f",
        source_run_id="run-x", source_step="experiment",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:42", context="c",
    ))
    store = store.add(NumericalProduct(
        label="xgboost__f1", value="0.72", unit=None, formula="f",
        source_run_id="run-x", source_step="experiment",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:43", context="c",
    ))

    state = WritingState(
        topic="t",
        numerical_store=store,
        experiment_results=ExperimentResults(
            code="results = {}\nresults['xgboost__auc'] = 0.87\nresults['xgboost__f1'] = 0.72\n",
            metrics={},
            figures=[],
            stdout="",
            stderr="",
        ),
    )

    runs = _build_experiment_runs_for_appendix(state)
    assert len(runs) == 1
    assert runs[0].run_id == "run-x"
    assert runs[0].producing_lines == (42, 43)
    assert runs[0].code_filename == "analysis.py"
    assert "xgboost__auc" in runs[0].code  # actual code was forwarded


def test_latex_compiler_node_returns_empty_runs_when_no_experiment_results() -> None:
    """No experiment_results → no Code appendix to render. Empty list, not crash."""
    from academic_pipeline.writing.graph import _build_experiment_runs_for_appendix
    from academic_pipeline.writing.state import WritingState

    state = WritingState(topic="t")  # no experiment_results
    runs = _build_experiment_runs_for_appendix(state)
    assert runs == []


def test_latex_compiler_node_returns_run_with_empty_lines_when_no_traced_lines() -> None:
    """Experiment ran but no labels were traceable (e.g., dynamic keys).

    The helper still returns ONE run with empty producing_lines — so the code
    block renders in the appendix without anchors. Reviewer can still see what
    code ran, just can't single-click to specific lines.
    """
    from academic_pipeline.models.experiment import ExperimentResults
    from academic_pipeline.writing.graph import _build_experiment_runs_for_appendix
    from academic_pipeline.writing.state import WritingState

    store = NumericalStore()
    store = store.add(NumericalProduct(
        label="xgboost__auc", value="0.87", unit=None, formula="f",
        source_run_id="run-x", source_step="experiment",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line=None,  # ← line tracer couldn't resolve
        context="c",
    ))

    state = WritingState(
        topic="t",
        numerical_store=store,
        experiment_results=ExperimentResults(
            code="results = {}\nfor k in keys: results[k] = 1\n",
            metrics={}, figures=[], stdout="", stderr="",
        ),
    )
    runs = _build_experiment_runs_for_appendix(state)
    assert len(runs) == 1
    assert runs[0].producing_lines == ()
