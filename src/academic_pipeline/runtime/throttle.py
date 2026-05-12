"""Rate limit throttle hook for Vertex AI quota protection."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic_ai.capabilities.hooks import Hooks

from academic_pipeline.config import DEFAULT_CONFIG


if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.models import ModelRequestContext


logger = logging.getLogger(__name__)


def make_throttle_hooks() -> Hooks:
    """Create a Hooks capability that throttles before each model request.

    Uses a closure-scoped counter so each Hooks instance tracks its own call count independently — no global mutable
    state.  Also logs all agent run errors centrally via ``on_run_error`` and
    transient model request failures via ``on_model_request_error``.
    """
    call_count = 0
    hooks = Hooks()

    @hooks.on.before_model_request
    async def throttle_before_request(
        _ctx: RunContext[object],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        nonlocal call_count
        call_count += 1
        delay = DEFAULT_CONFIG.tool_call_delay_seconds

        if call_count <= 1:
            return request_context

        if delay > 0:
            logger.debug("Throttling %ds before model request #%d", delay, call_count)
            await asyncio.sleep(delay)
        return request_context

    @hooks.on.run_error
    async def log_agent_error(ctx: RunContext[object], *, error: BaseException) -> None:  # type: ignore[return-type]
        logger.error(
            "Agent run failed: %s (retry=%d): %s",
            type(error).__name__,
            ctx.retry,
            error,
        )
        raise error

    @hooks.on.model_request_error
    async def log_model_request_error(
        ctx: RunContext[object],
        *,
        request_context: ModelRequestContext,
        error: Exception,
    ) -> None:  # type: ignore[return-type]
        logger.warning(
            "Model request failed (will retry): %s: %s",
            type(error).__name__,
            error,
        )
        raise error

    return hooks


throttle_hooks = make_throttle_hooks()
