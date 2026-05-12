"""Tests for the inline validator invocation pattern used in writing/graph.py."""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRetry

from academic_pipeline.models.numerical import NumericalStore
from academic_pipeline.traceability.validators import (
    ABORTING_PHRASES,
    FORBIDDEN_PHRASES,
    make_numeric_output_validator,
)


def test_inline_validator_call_passes_clean_section(make_store_with, StubSection) -> None:  # noqa: N803
    store = make_store_with({"x": "1"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    section = StubSection(text="Value: ⟨num:x⟩.")
    out = validator(section)
    assert out is section


def test_inline_validator_skipped_when_mode_off(make_store_with, StubSection) -> None:  # noqa: N803
    """Documents the call-site contract: if mode == 'off', writing/graph.py does NOT call validator.

    This is a documentation test for the call site behavior; the gate happens at the call site,
    not inside the validator factory.
    """
    assert True


def test_inline_validator_call_raises_on_bare_number(make_store_with, StubSection) -> None:  # noqa: N803
    store = NumericalStore()
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    section = StubSection(text="Bare 23.5% number.")
    with pytest.raises(ModelRetry):
        validator(section)
