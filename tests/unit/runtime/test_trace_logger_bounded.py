"""Test that traced_agent_run uses bounded_agent_run with default timeout."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from academic_pipeline.recovery.bounded_run import AgentTimeoutError


class _SlowAgent:
    async def run(self, context: str, **kwargs: object) -> str:
        await asyncio.sleep(5)
        return "should not get here"


@pytest.mark.asyncio
async def test_traced_agent_run_respects_bounded_run_timeout(tmp_path) -> None:
    from academic_pipeline.runtime.trace_logger import traced_agent_run

    deps_mock = type("D", (), {"trace_logger": None})()

    with patch(
        "academic_pipeline.runtime.trace_logger._AGENT_RUN_TIMEOUT_S",
        0.2,
    ), pytest.raises(AgentTimeoutError):
        await traced_agent_run(
            _SlowAgent(),
            context="x",
            deps=deps_mock,
            name="test",
            phase="test",
        )
