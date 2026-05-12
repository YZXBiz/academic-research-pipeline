"""Tests for build_curated_context with ContextSpec."""

from __future__ import annotations

from dataclasses import dataclass, field

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.runtime.context import build_curated_context
from academic_pipeline.traceability.context_spec import ContextSpec


@dataclass
class _StubState:
    research_synthesis: str = "synthesis text"
    other_field: str = "should be excluded"
    numerical_store: NumericalStore = field(default_factory=NumericalStore)


def _store_with(label: str, value: str, ctx: str) -> NumericalStore:
    return NumericalStore().add(NumericalProduct(
        label=label, value=value, unit="%", formula="f",
        source_run_id="r", source_step="s", source_artifact="a",
        source_code_line=None, context=ctx,
    ))


def test_curated_context_includes_only_allowed_products() -> None:
    state = _StubState(numerical_store=_store_with("pct_a", "23.5", "Prevalence"))
    spec = ContextSpec(allowed_products=["research_synthesis"], allowed_numerical_labels="all")
    out = build_curated_context(state, spec)
    assert "synthesis text" in out
    assert "should be excluded" not in out


def test_curated_context_includes_numerical_labels_when_all() -> None:
    state = _StubState(numerical_store=_store_with("pct_a", "23.5", "Prevalence"))
    spec = ContextSpec(allowed_products=["research_synthesis"], allowed_numerical_labels="all")
    out = build_curated_context(state, spec)
    assert "pct_a" in out
    assert "23.5" in out


def test_curated_context_filters_numerical_labels_to_subset() -> None:
    store = _store_with("pct_a", "23.5", "Prevalence A")
    store = store.add(NumericalProduct(
        label="pct_b", value="42.0", unit=None, formula="f",
        source_run_id="r", source_step="s", source_artifact="a",
        source_code_line=None, context="Prevalence B",
    ))
    state = _StubState(numerical_store=store)
    spec = ContextSpec(allowed_products=["research_synthesis"], allowed_numerical_labels=["pct_a"])
    out = build_curated_context(state, spec)
    assert "pct_a" in out
    assert "pct_b" not in out


def test_curated_context_omits_numerical_section_when_store_empty() -> None:
    state = _StubState()  # default empty store
    spec = ContextSpec(allowed_products=["research_synthesis"], allowed_numerical_labels="all")
    out = build_curated_context(state, spec)
    # The numerical-values table header should not appear when store is empty
    assert "Available numerical values" not in out
    assert "synthesis text" in out  # but the rest of the context still works


def test_curated_context_skips_missing_state_fields() -> None:
    """Allowed products that don't exist on state are silently skipped (matches build_context behavior)."""
    state = _StubState()
    spec = ContextSpec(
        allowed_products=["research_synthesis", "nonexistent_field"],
        allowed_numerical_labels="all",
    )
    out = build_curated_context(state, spec)
    assert "synthesis text" in out
    assert "nonexistent_field" not in out
