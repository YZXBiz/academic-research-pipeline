"""Tests for the AgentTimeoutError + bounded_agent_run wrapper."""

from __future__ import annotations

import asyncio

import pytest

from academic_pipeline.recovery.bounded_run import (
    AgentTimeoutError,
    bounded_agent_run,
)


class _StubAgent:
    """Minimal agent stub exposing an async run() method."""

    def __init__(self, sleep_s: float = 0.0, return_value: object = "ok") -> None:
        self._sleep_s = sleep_s
        self._return_value = return_value

    async def run(self, context: str, **kwargs: object) -> object:
        await asyncio.sleep(self._sleep_s)
        return self._return_value


@pytest.mark.asyncio
async def test_bounded_agent_run_returns_result_on_success() -> None:
    agent = _StubAgent(sleep_s=0.01, return_value="hello")
    result = await bounded_agent_run(agent, "ctx", timeout_s=5.0)
    assert result == "hello"


@pytest.mark.asyncio
async def test_bounded_agent_run_raises_agent_timeout_error_on_timeout() -> None:
    agent = _StubAgent(sleep_s=2.0)
    with pytest.raises(AgentTimeoutError) as exc_info:
        await bounded_agent_run(agent, "ctx", timeout_s=0.2)
    assert "0.2" in str(exc_info.value)


@pytest.mark.asyncio
async def test_bounded_agent_run_passes_kwargs_through() -> None:
    captured: dict[str, object] = {}

    class _CapturingAgent:
        async def run(self, context: str, **kwargs: object) -> str:
            captured["context"] = context
            captured["kwargs"] = kwargs
            return "captured"

    result = await bounded_agent_run(
        _CapturingAgent(),
        "the-context",
        timeout_s=5.0,
        deps="my-deps",
        message_history=[1, 2],
    )
    assert result == "captured"
    assert captured["context"] == "the-context"
    assert captured["kwargs"] == {"deps": "my-deps", "message_history": [1, 2]}


def test_agent_timeout_error_is_runtime_error() -> None:
    assert issubclass(AgentTimeoutError, RuntimeError)
