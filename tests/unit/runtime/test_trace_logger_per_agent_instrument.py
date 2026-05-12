"""Tests for per-agent logfire instrumentation in traced_agent_run (PRD §6.13.T3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio()
async def test_traced_agent_run_instruments_agent_per_call() -> None:
    """PRD §6.13.T3 — traced_agent_run calls logfire.instrument_pydantic_ai(agent)
    so each span carries per-agent identity, instead of relying on the global
    instrument_pydantic_ai() call.
    """
    from academic_pipeline.runtime import trace_logger as tl

    agent = SimpleNamespace(name="my_test_agent")
    deps = SimpleNamespace(trace_logger=None)

    with (
        patch.object(tl, "_instrumented_agents", set()),
        patch("logfire.instrument_pydantic_ai") as mock_instrument,
        patch(
            "academic_pipeline.recovery.bounded_run.bounded_agent_run",
            return_value=SimpleNamespace(output="x"),
        ),
    ):
        await tl.traced_agent_run(agent, "ctx", deps=deps, name="n", phase="p")
        mock_instrument.assert_called_once_with(agent)


@pytest.mark.asyncio()
async def test_traced_agent_run_does_not_double_instrument_same_agent() -> None:
    """Idempotency: instrumenting the same agent twice would double-emit spans."""
    from academic_pipeline.runtime import trace_logger as tl

    agent = SimpleNamespace(name="agent_a")
    deps = SimpleNamespace(trace_logger=None)

    with (
        patch.object(tl, "_instrumented_agents", set()),
        patch("logfire.instrument_pydantic_ai") as mock_instrument,
        patch(
            "academic_pipeline.recovery.bounded_run.bounded_agent_run",
            return_value=SimpleNamespace(output="x"),
        ),
    ):
        await tl.traced_agent_run(agent, "ctx", deps=deps, name="n", phase="p")
        await tl.traced_agent_run(agent, "ctx2", deps=deps, name="n", phase="p")
        mock_instrument.assert_called_once_with(agent)


@pytest.mark.asyncio()
async def test_traced_agent_run_continues_when_logfire_unavailable() -> None:
    """When logfire isn't importable, the call must continue (no raise)."""
    from academic_pipeline.runtime import trace_logger as tl

    agent = SimpleNamespace(name="agent_b")
    deps = SimpleNamespace(trace_logger=None)

    with (
        patch.object(tl, "_instrumented_agents", set()),
        patch.dict("sys.modules", {"logfire": None}),
        patch(
            "academic_pipeline.recovery.bounded_run.bounded_agent_run",
            return_value=SimpleNamespace(output="x"),
        ),
    ):
        # Should not raise
        result = await tl.traced_agent_run(agent, "ctx", deps=deps, name="n", phase="p")
        assert result.output == "x"


def test_configure_observability_no_longer_calls_global_instrument() -> None:
    """PRD §6.13.T3 — global instrument_pydantic_ai() removed in favor of
    per-agent instrumentation in traced_agent_run."""
    from academic_pipeline import observability

    mock_logfire = MagicMock()
    with patch.dict("sys.modules", {"logfire": mock_logfire}):
        observability.configure_observability()
    mock_logfire.instrument_pydantic_ai.assert_not_called()
