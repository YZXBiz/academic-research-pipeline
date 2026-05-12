"""Tests for AgentMessageCache integration in InteractiveMLNode."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from academic_pipeline.tools.agent_cache import AgentMessageCache


if TYPE_CHECKING:
    from pathlib import Path


def _sample_messages() -> list[ModelRequest | ModelResponse]:
    return [
        ModelRequest(parts=[UserPromptPart(content="Run experiment")]),
        ModelResponse(parts=[TextPart(content="Starting AutoGluon training...")]),
    ]


def test_cache_created_in_correct_directory(tmp_path: Path) -> None:
    """Cache dir should be output/<run-id>/02-experiment/cache/."""
    cache_dir = str(tmp_path / "02-experiment" / "cache")
    cache = AgentMessageCache(cache_dir=cache_dir, agent_name="ml_engineer")
    assert cache.cache_path == tmp_path / "02-experiment" / "cache" / "ml_engineer.json"
    assert cache.cache_dir.exists()


@pytest.mark.asyncio
async def test_traced_agent_run_forwards_message_history() -> None:
    """traced_agent_run passes message_history= through to agent.run()."""
    from academic_pipeline.runtime.trace_logger import traced_agent_run

    messages = _sample_messages()
    mock_agent = AsyncMock()
    mock_result = MagicMock()
    mock_result.output = "test"
    mock_agent.run = AsyncMock(return_value=mock_result)

    deps = MagicMock()
    deps.trace_logger = None

    await traced_agent_run(
        mock_agent, "test context", deps=deps,
        name="test", phase="test",
        message_history=messages,
    )

    mock_agent.run.assert_called_once()
    call_kwargs = mock_agent.run.call_args.kwargs
    assert call_kwargs["message_history"] is messages


@pytest.mark.asyncio
async def test_traced_agent_run_none_message_history() -> None:
    """message_history=None should be a valid no-op."""
    from academic_pipeline.runtime.trace_logger import traced_agent_run

    mock_agent = AsyncMock()
    mock_result = MagicMock()
    mock_result.output = "test"
    mock_agent.run = AsyncMock(return_value=mock_result)

    deps = MagicMock()
    deps.trace_logger = None

    await traced_agent_run(
        mock_agent, "test context", deps=deps,
        name="test", phase="test",
        message_history=None,
    )

    call_kwargs = mock_agent.run.call_args.kwargs
    assert call_kwargs["message_history"] is None
