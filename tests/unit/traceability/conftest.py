"""Shared fixtures for traceability tests.

Defined here to prevent duplication of StubSection / make_store_with across the
~10 test files in this subdirectory.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from academic_pipeline.models.numerical import NumericalProduct, NumericalStore


@pytest.fixture
def StubSection():  # noqa: N802 — fixture returns a class; uppercase name reflects that
    @dataclass
    class _StubSection:
        text: str
        section_name: str = "results"
    return _StubSection


@pytest.fixture
def make_store_with():
    def _make(label_to_value: dict[str, str]) -> NumericalStore:
        store = NumericalStore()
        for label, value in label_to_value.items():
            store = store.add(NumericalProduct(
                label=label, value=value, unit=None, formula="f",
                source_run_id="r", source_step="s", source_artifact="a",
                source_code_line=None, context="c",
            ))
        return store
    return _make
