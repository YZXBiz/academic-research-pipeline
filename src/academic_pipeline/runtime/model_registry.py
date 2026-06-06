"""Single source of truth for per-agent model selection + inference settings.

Every agent in the pipeline is constructed through :func:`build_agent`, which
injects the model and any provider-specific reasoning settings from
configuration rather than from the YAML spec. The specs therefore carry no
model literal: the underlying model is a *configuration concern*
(``config.default_model`` + ``config.model_overrides``), not a string scattered
across 53 files.

Flip the whole pipeline between providers by setting ``DEFAULT_MODEL`` in
``.env`` — e.g. ``openai:deepseek-v4-pro`` -> ``anthropic:claude-opus-4-8``.
Per-agent exceptions (true cross-model verification, cost lanes) go in
``MODEL_OVERRIDES``. This mirrors the provider-string-routing pattern: one
``provider:model`` string at a single call site, credentials from env, no
provider SDK type at any call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModelSettings

from academic_pipeline.config import DEFAULT_CONFIG


if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.settings import ModelSettings

    from academic_pipeline.core.deps import PipelineDeps


# Agents that run at maximum reasoning effort. The *what* (max reasoning) is
# agent-stable and lives here; the *how* (provider-specific request shape) is
# resolved per-provider in `model_settings_for`. Keeping this in code — not in
# the specs — is precisely what lets the specs stay provider-neutral.
MAX_REASONING_AGENTS: frozenset[str] = frozenset(
    {
        "independent_verifier",
        "eic",
        "field_analyst",
        "domain_reviewer",
        "methodology_reviewer",
        "perspective_reviewer",
        "editorial_synthesizer",
        "claim_extractor",
        "claim_novelty_assessor",
        "senior_gatekeeper_reviewer",
        "applied_practitioner_reviewer",
        "methodology_purist_reviewer",
        "numerical_claims_auditor",
        "citation_grounding",
        "figure_verifier",
    }
)


def resolve_model(agent_key: str | None = None) -> str:
    """Return the provider-prefixed model string for an agent.

    Per-agent entries in ``config.model_overrides`` win; everything else uses
    ``config.default_model``. This is the only place an agent -> model decision
    is made.
    """
    if agent_key is not None:
        override = DEFAULT_CONFIG.model_overrides.get(agent_key)
        if override:
            return override
    return DEFAULT_CONFIG.default_model


def model_settings_for(agent_key: str, model: str | None = None) -> ModelSettings | None:
    """Provider-translated inference settings for an agent, or ``None``.

    Only :data:`MAX_REASONING_AGENTS` receive non-``None`` settings. The
    max-reasoning request shape differs per provider — DeepSeek/OpenAI use
    ``extra_body.thinking.reasoning_effort``; Anthropic uses
    ``anthropic_thinking`` with a token budget — so it cannot live in a
    provider-neutral spec. Returned settings are merged *additively* over the
    spec's own ``model_settings`` (e.g. ``max_tokens``) by ``Agent.from_file``.
    """
    if agent_key not in MAX_REASONING_AGENTS:
        return None
    resolved = model if model is not None else resolve_model(agent_key)
    provider = resolved.split(":", 1)[0]
    if provider in {"openai", "deepseek"}:
        return OpenAIChatModelSettings(
            extra_body={"thinking": {"type": "enabled", "reasoning_effort": "max"}}
        )
    if provider == "anthropic":
        # budget_tokens must stay below the spec's max_tokens (>=16000 for these
        # agents); 8192 is a safe high-reasoning budget under every current cap.
        return AnthropicModelSettings(
            anthropic_thinking={"type": "enabled", "budget_tokens": 8192}
        )
    return None


def build_agent(agent_key: str, spec_path: Path | str, **kwargs: Any) -> Agent[PipelineDeps, Any]:
    """Construct an agent from a spec with centrally-resolved model + settings.

    Replaces direct ``Agent.from_file`` at every registry call site: the model
    and any provider-specific reasoning settings are injected here from config,
    so the specs carry neither. Spec-level ``model_settings`` (``max_tokens``,
    ``temperature``) still apply — injected settings merge over them.
    """
    settings = model_settings_for(agent_key)
    if settings is not None:
        kwargs["model_settings"] = settings
    return Agent.from_file(spec_path, model=resolve_model(agent_key), **kwargs)
