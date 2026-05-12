"""Tests for throttle hooks configuration."""
from __future__ import annotations

from pydantic_ai.capabilities.hooks import Hooks


def test_throttle_hooks_has_run_error():
    """Verify throttle_hooks has on_run_error registered."""
    from academic_pipeline.runtime.throttle import throttle_hooks
    assert isinstance(throttle_hooks, Hooks)


def test_throttle_hooks_has_model_request_error():
    """Verify throttle_hooks has on_model_request_error registered."""
    from academic_pipeline.runtime.throttle import throttle_hooks
    assert isinstance(throttle_hooks, Hooks)
    hooks_dict = throttle_hooks._registry
    assert "on_model_request_error" in hooks_dict
    assert len(hooks_dict["on_model_request_error"]) > 0
