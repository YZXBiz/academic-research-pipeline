"""Test that the 3 agent.run sites in evaluator are bounded."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_evaluator_module_uses_bounded_run() -> None:
    """Smoke check: importing evaluator pulls in bounded_agent_run symbol."""
    import academic_pipeline.runtime.evaluator as evaluator

    assert hasattr(evaluator, "bounded_agent_run")
