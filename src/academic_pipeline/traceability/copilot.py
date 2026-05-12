"""Copilot checkpoint — optional 1-sentence stdin comment at named pipeline boundaries.

Three call sites in the pipeline (wired in Task 18):
- post-research (after IntakeNode)
- post-experiment-design (after ExperimentPhaseNode)
- post-first-draft (after WritePhaseNode)

Disabled by default. When enabled (--copilot flag / config.copilot_enabled),
each checkpoint reads stdin with timeout. Comment becomes part of the next
agent's context via deps.copilot_comments.

Per data-to-paper's reported numbers: 2-3 single-sentence comments turn
90% error rate (complex tasks) → 10-20%. Massive reliability lever for
near-zero human effort.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable


logger = logging.getLogger(__name__)


async def _default_stdin_reader(timeout: float) -> str:
    """Async stdin readline with timeout. Raises TimeoutError on timeout."""
    loop = asyncio.get_running_loop()
    try:
        line = await asyncio.wait_for(
            loop.run_in_executor(None, sys.stdin.readline),
            timeout=timeout,
        )
    except TimeoutError as e:
        raise TimeoutError("stdin read timeout") from e
    return line


# Type alias for the stdin reader: either an async function or a sync function
# (sync allowed mainly for ergonomic test stubs that don't need asyncio).
StdinReader = Callable[[float], Awaitable[str]] | Callable[[float], str]


async def copilot_checkpoint(
    *,
    name: str,
    summary: str,
    timeout_s: int = 60,
    enabled: bool = True,
    stdin_reader: StdinReader = _default_stdin_reader,
) -> str | None:
    """Read a 1-sentence comment from stdin with timeout.

    Returns the trimmed comment, or None on disabled / timeout / empty input.
    Whitespace-only input is treated as empty.
    """
    if not enabled:
        return None
    print(f"\n[copilot:{name}] {summary}\nComment ({timeout_s}s, empty=continue): ", flush=True)
    try:
        result = stdin_reader(timeout_s)
        if asyncio.iscoroutine(result):
            line = await result
        else:
            line = result  # type: ignore[assignment]
    except TimeoutError:
        logger.warning("copilot:%s timeout after %ds; continuing autonomously", name, timeout_s)
        return None
    line_str: str = line.strip() if isinstance(line, str) else ""
    return line_str or None
