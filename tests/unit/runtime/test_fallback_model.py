"""Tests for FallbackModel on Anthropic evaluator agents."""
from __future__ import annotations


def test_evaluator_skips_fallback_for_anthropic():
    """Verify non-OpenAI evaluator agents use plain model string."""
    from pydantic_ai.models.fallback import FallbackModel

    from academic_pipeline.runtime.evaluator import _get_evaluator_agent

    agent = _get_evaluator_agent("anthropic:claude-opus-4-7")
    assert not isinstance(agent.model, FallbackModel)
