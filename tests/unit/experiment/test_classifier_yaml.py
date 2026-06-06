"""Tests for experiment_classifier.yaml prompt content."""
from __future__ import annotations

from pathlib import Path


def _yaml_text() -> str:
    return Path("src/academic_pipeline/experiment/specs/experiment_classifier.yaml").read_text()


def test_yaml_loads_via_pydantic_ai() -> None:
    from academic_pipeline.runtime.model_registry import build_agent
    agent = build_agent(
        "experiment_classifier",
        "src/academic_pipeline/experiment/specs/experiment_classifier.yaml",
    )
    assert agent is not None


def test_yaml_explains_null_predictor_type_when_no_experiments() -> None:
    text = _yaml_text().lower()
    # Must explicitly say to set null/None when no experiments
    assert "null" in text or "none" in text
    # And must reference the no-experiments case
    assert "needs_experiments=false" in text or "not needed" in text or "no experiments" in text


def test_yaml_lists_three_predictor_types() -> None:
    text = _yaml_text()
    assert "tabular" in text
    assert "timeseries" in text
    assert "multimodal" in text
