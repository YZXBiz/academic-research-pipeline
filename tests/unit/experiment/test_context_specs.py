"""Tests for experiment-subgraph per-agent ContextSpec instances (PRD §6.10.T3)."""

from __future__ import annotations

from academic_pipeline.experiment.context_specs import RESULT_ANALYZER_CONTEXT_SPEC
from academic_pipeline.traceability.context_spec import ContextSpec


def test_result_analyzer_spec_is_a_context_spec() -> None:
    assert isinstance(RESULT_ANALYZER_CONTEXT_SPEC, ContextSpec)


def test_result_analyzer_spec_lists_state_fields_actually_read() -> None:
    """result_analyzer's existing call site reads topic, rq_brief, synthesis,
    and results — see experiment/graph.py:794."""
    expected = {"topic", "rq_brief", "synthesis", "results"}
    assert set(RESULT_ANALYZER_CONTEXT_SPEC.allowed_products) == expected


def test_result_analyzer_grants_full_numerical_store_access() -> None:
    """result_analyzer is responsible for citing experiment numbers — needs
    full numerical_store access."""
    assert RESULT_ANALYZER_CONTEXT_SPEC.allowed_numerical_labels == "all"


def test_result_analyzer_call_site_uses_curated_context() -> None:
    """The result_analyzer invocation in experiment/graph.py must reference
    RESULT_ANALYZER_CONTEXT_SPEC + build_curated_context."""
    import inspect

    from academic_pipeline.experiment import graph

    source = inspect.getsource(graph)
    assert "RESULT_ANALYZER_CONTEXT_SPEC" in source
    # The result_analyzer block must use curated context (cannot just be the import)
    assert "build_curated_context" in source
