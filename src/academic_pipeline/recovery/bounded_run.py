"""Bounded agent.run wrapper — caps single LLM calls at a wall-clock budget.

Catches the LEGITIMATE-slow case (LLM is actually thinking for >15min). Does
NOT save us from blocked sync recv() — that is L2/L4's job (asyncio.wait_for
cannot preempt a sync syscall blocked in the kernel; verified via socketpair
test in research synthesis).

Generic over the agent's deps and output types so callers preserve type
safety end-to-end:

    result: AgentRunResult[MyOutput] = await bounded_agent_run(
        my_agent,                  # Agent[MyDeps, MyOutput]
        "context",
        deps=my_deps,
    )
    typed_output: MyOutput = result.output
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar


if TYPE_CHECKING:
    from pydantic_ai import Agent, AgentRunResult


_TDeps = TypeVar("_TDeps")
_TOutput = TypeVar("_TOutput")


class AgentTimeoutError(RuntimeError):
    """Raised when an agent.run() call exceeds its wall-clock budget."""


async def bounded_agent_run(
    agent: Agent[_TDeps, _TOutput],
    context: str,
    *,
    timeout_s: float = 900.0,
    **kwargs: Any,
) -> AgentRunResult[_TOutput]:
    """Run an agent with a hard wall-clock cap.

    Args:
        agent: A pydantic-ai ``Agent[TDeps, TOutput]``. The output type
            parameter flows through to the returned ``AgentRunResult``.
        context: First positional arg forwarded to ``agent.run``.
        timeout_s: Wall-clock budget in seconds. Default 900 (15 minutes).
        **kwargs: Forwarded verbatim to ``agent.run`` (typed as Any because
            pydantic-ai's run kwargs — ``deps``, ``message_history``,
            ``usage_limits`` — have shifting signatures across versions).

    Returns:
        ``AgentRunResult[TOutput]`` from the agent's run.

    Raises:
        AgentTimeoutError: If the agent did not return within ``timeout_s``.
    """
    try:
        return await asyncio.wait_for(agent.run(context, **kwargs), timeout=timeout_s)
    except TimeoutError as exc:
        raise AgentTimeoutError(
            f"agent.run exceeded {timeout_s}s wall-clock budget"
        ) from exc
