"""Tests for NumericalProduct and NumericalStore."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore


def test_numerical_product_required_fields():
    p = NumericalProduct(
        label="pct_high_hba1c",
        value="23.5",
        unit="%",
        formula="100 * mean(hba1c > 8) for diabetic subset",
        source_run_id="run-x",
        source_step="experiment.analysis",
        source_artifact="output/run-x/code/analysis.py",
        source_code_line="analysis.py:42",
        context="Prevalence of poor glycemic control among elderly diabetics",
    )
    assert p.label == "pct_high_hba1c"
    assert p.value == "23.5"


def test_numerical_product_is_frozen():
    p = NumericalProduct(
        label="x", value="1", unit=None, formula="f", source_run_id="r",
        source_step="s", source_artifact="a", source_code_line=None, context="c",
    )
    with pytest.raises(ValidationError):
        p.value = "2"  # type: ignore[misc]


def test_numerical_store_add_returns_new_instance():
    store = NumericalStore(products={})
    p = NumericalProduct(
        label="x", value="1", unit=None, formula="f", source_run_id="r",
        source_step="s", source_artifact="a", source_code_line=None, context="c",
    )
    new_store = store.add(p)
    assert "x" in new_store.products
    assert "x" not in store.products  # original unchanged


def test_numerical_store_add_duplicate_raises():
    from academic_pipeline.traceability.errors import StoreIntegrityError
    p = NumericalProduct(
        label="x", value="1", unit=None, formula="f", source_run_id="r",
        source_step="s", source_artifact="a", source_code_line=None, context="c",
    )
    store = NumericalStore(products={"x": p})
    with pytest.raises(StoreIntegrityError):
        store.add(p)
