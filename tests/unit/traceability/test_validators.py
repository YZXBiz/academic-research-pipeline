"""Tests for numeric_output_validator factory.

StubSection and make_store_with come from tests/unit/traceability/conftest.py fixtures.
"""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior

from academic_pipeline.traceability.validators import (
    ABORTING_PHRASES,
    FORBIDDEN_PHRASES,
    HEDGE_PROXIMITY_TOKENS,
    make_numeric_output_validator,
)


def test_validator_passes_clean_output(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_a": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    result = validator(StubSection(text="The value is ⟨num:pct_a⟩ in the cohort."))
    assert result.text == "The value is ⟨num:pct_a⟩ in the cohort."


def test_validator_rejects_unwrapped_number(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    with pytest.raises(ModelRetry) as exc:
        validator(StubSection(text="The value is 23.5% in the cohort."))
    assert "23.5" in str(exc.value) or "wrap" in str(exc.value).lower()


def test_validator_rejects_unknown_label(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_a": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    with pytest.raises(ModelRetry) as exc:
        validator(StubSection(text="The value is ⟨num:does_not_exist⟩."))
    assert "does_not_exist" in str(exc.value)


def test_validator_aborts_on_aborting_phrase(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_a": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    with pytest.raises(UnexpectedModelBehavior) as exc:
        validator(StubSection(text="Results are ⟨num:pct_a⟩ [subject to revision]."))
    assert "subject to revision" in str(exc.value).lower()


def test_validator_rejects_hedge_near_number(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_a": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    with pytest.raises(ModelRetry) as exc:
        validator(StubSection(text="Approximately ⟨num:pct_a⟩ patients had X."))
    assert "approximately" in str(exc.value).lower() or "hedge" in str(exc.value).lower()


def test_validator_allows_hedge_far_from_number(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_a": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    text = "Approximately " + ("filler " * (HEDGE_PROXIMITY_TOKENS + 2)) + "the rate was ⟨num:pct_a⟩."
    result = validator(StubSection(text=text))
    assert result.text == text


def test_validator_allows_numbers_inside_num_token(make_store_with, StubSection):  # noqa: N803
    store = make_store_with({"pct_25": "1.0"})
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    result = validator(StubSection(text="Result is ⟨num:pct_25⟩."))
    assert result.text == "Result is ⟨num:pct_25⟩."
