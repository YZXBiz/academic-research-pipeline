"""Unit tests for the central model registry (single source of truth for
per-agent model selection + provider-translated inference settings)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from academic_pipeline.config import DEFAULT_CONFIG
from academic_pipeline.runtime.model_registry import (
    MAX_REASONING_AGENTS,
    model_settings_for,
    resolve_model,
)


if TYPE_CHECKING:
    import pytest


def _all_registry_keys() -> set[str]:
    from academic_pipeline.experiment.agents import agents as experiment_agents
    from academic_pipeline.integrity.agents import agents as integrity_agents
    from academic_pipeline.research.agents import agents as research_agents
    from academic_pipeline.review.agents import agents as review_agents
    from academic_pipeline.writing.agents import agents as writing_agents

    keys: set[str] = set()
    for registry in (
        research_agents,
        review_agents,
        writing_agents,
        experiment_agents,
        integrity_agents,
    ):
        keys |= set(registry)
    return keys


class TestResolveModel:
    def test_no_key_returns_default(self) -> None:
        assert resolve_model() == DEFAULT_CONFIG.default_model

    def test_unknown_key_returns_default(self) -> None:
        assert resolve_model("not_a_real_agent") == DEFAULT_CONFIG.default_model

    def test_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DEFAULT_CONFIG,
            "model_overrides",
            {"independent_verifier": "anthropic:claude-opus-4-8"},
        )
        assert resolve_model("independent_verifier") == "anthropic:claude-opus-4-8"
        # An agent absent from the map still falls back to default.
        assert resolve_model("eic") == DEFAULT_CONFIG.default_model

    def test_empty_override_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(DEFAULT_CONFIG, "model_overrides", {"eic": ""})
        assert resolve_model("eic") == DEFAULT_CONFIG.default_model


class TestModelSettingsFor:
    def test_non_reasoning_agent_gets_none(self) -> None:
        assert model_settings_for("intake") is None
        assert model_settings_for("draft_writer") is None

    def test_deepseek_reasoning_uses_extra_body_thinking(self) -> None:
        settings = model_settings_for("eic", model="openai:deepseek-v4-pro")
        assert settings is not None
        s = cast("dict[str, Any]", settings)
        assert s["extra_body"]["thinking"]["reasoning_effort"] == "max"

    def test_anthropic_reasoning_uses_anthropic_thinking(self) -> None:
        settings = model_settings_for("eic", model="anthropic:claude-opus-4-8")
        assert settings is not None
        thinking = cast("dict[str, Any]", settings)["anthropic_thinking"]
        assert thinking["type"] == "enabled"
        # budget must stay below the smallest reasoning-agent max_tokens (16000).
        assert 0 < thinking["budget_tokens"] < 16000

    def test_unknown_provider_reasoning_returns_none(self) -> None:
        assert model_settings_for("eic", model="cohere:command-r") is None


def test_max_reasoning_agents_are_real_registry_keys() -> None:
    """Drift guard: every name in MAX_REASONING_AGENTS must exist as an agent,
    so a typo can never silently drop an agent's max-reasoning setting."""
    unknown = MAX_REASONING_AGENTS - _all_registry_keys()
    assert not unknown, f"MAX_REASONING_AGENTS names not found in any registry: {unknown}"
