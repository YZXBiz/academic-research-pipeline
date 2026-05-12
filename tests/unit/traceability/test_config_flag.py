"""Tests for traceability_mode config flag and numerical_store state field."""

from __future__ import annotations

from academic_pipeline.config import PipelineConfig
from academic_pipeline.models.numerical import NumericalStore
from academic_pipeline.pipeline.state import PipelineState


def test_traceability_mode_defaults_off() -> None:
    config = PipelineConfig(anthropic_api_key="sk-test")  # type: ignore[arg-type]
    assert config.traceability_mode == "off"


def test_traceability_mode_accepts_partial_full() -> None:
    for mode in ("off", "partial", "full"):
        config = PipelineConfig(anthropic_api_key="sk-test", traceability_mode=mode)  # type: ignore[arg-type]
        assert config.traceability_mode == mode


def test_copilot_enabled_defaults_false() -> None:
    config = PipelineConfig(anthropic_api_key="sk-test")  # type: ignore[arg-type]
    assert config.copilot_enabled is False


def test_max_dialogue_turns_defaults_3() -> None:
    config = PipelineConfig(anthropic_api_key="sk-test")  # type: ignore[arg-type]
    assert config.max_dialogue_turns == 3


def test_pipeline_state_has_numerical_store_default_empty() -> None:
    """PipelineState must carry a NumericalStore (default empty) so the producer seam can populate it."""
    state = PipelineState(topic="x")
    assert isinstance(state.numerical_store, NumericalStore)
    assert state.numerical_store.products == {}
