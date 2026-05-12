"""Regression suite — every known historical fabrication that the eval panel
passed at 9/10 must now fail validation. Add one new fixture here per future
fabrication caught in production.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore
from academic_pipeline.traceability.validators import (
    ABORTING_PHRASES,
    FORBIDDEN_PHRASES,
    make_numeric_output_validator,
)


@dataclass(frozen=True)
class HistoricalFabrication:
    name: str
    section_text: str
    available_labels: tuple[str, ...] = ()
    expected_exception: type[Exception] = ModelRetry


@dataclass
class _StubSection:
    text: str
    section_name: str = "results"


def _make_store(labels: tuple[str, ...]) -> NumericalStore:
    store = NumericalStore()
    for label in labels:
        store = store.add(NumericalProduct(
            label=label, value="1.0", unit=None, formula="f",
            source_run_id="r", source_step="s", source_artifact="a",
            source_code_line=None, context="c",
        ))
    return store


REGRESSIONS: list[HistoricalFabrication] = [
    HistoricalFabrication(
        name="pooled_estimate_from_thin_synthesis",
        section_text="Pooled OR was 1.42 (95% CI 1.18-1.71), heterogeneity I² = 23%.",
        available_labels=(),
        expected_exception=ModelRetry,
    ),
    HistoricalFabrication(
        name="hedged_specific_number",
        section_text="Approximately ⟨num:pct_high_hba1c⟩ of patients had elevated HbA1c.",
        available_labels=("pct_high_hba1c",),
        expected_exception=ModelRetry,
    ),
    HistoricalFabrication(
        name="placeholder_subject_to_revision",
        section_text="Results: ⟨num:pct_high_hba1c⟩ patients improved (subject to revision).",
        available_labels=("pct_high_hba1c",),
        expected_exception=UnexpectedModelBehavior,
    ),
]


@pytest.mark.parametrize("fixture", REGRESSIONS, ids=lambda f: f.name)
def test_validator_catches_historical_fabrication(fixture: HistoricalFabrication) -> None:
    store = _make_store(fixture.available_labels)
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)
    with pytest.raises(fixture.expected_exception):
        validator(_StubSection(text=fixture.section_text))
