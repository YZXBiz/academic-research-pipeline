"""Tests for ContextSpec curated-context model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.traceability.context_spec import ContextSpec


def test_context_spec_holds_allowed_products_and_labels():
    spec = ContextSpec(
        allowed_products=["research.synthesis", "experiment.results"],
        allowed_numerical_labels="all",
    )
    assert spec.allowed_products == ["research.synthesis", "experiment.results"]
    assert spec.allowed_numerical_labels == "all"


def test_context_spec_allowed_labels_can_be_list():
    spec = ContextSpec(
        allowed_products=["research.synthesis"],
        allowed_numerical_labels=["pct_a", "pct_b"],
    )
    assert spec.allowed_numerical_labels == ["pct_a", "pct_b"]


def test_context_spec_is_frozen():
    spec = ContextSpec(allowed_products=["x"], allowed_numerical_labels="all")
    with pytest.raises(ValidationError):
        spec.allowed_products = ["y"]  # type: ignore[misc]
