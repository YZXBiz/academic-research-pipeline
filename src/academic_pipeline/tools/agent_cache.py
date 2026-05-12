"""Agent message cache for crash recovery and judge loop resume.

Persists PydanticAI agent message history to disk so a crashed or
looping pipeline can resume mid-conversation instead of starting fresh.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

logger = logging.getLogger(__name__)


class AgentMessageCache:
    """Persists PydanticAI agent message history for conversation resume."""

    def __init__(self, cache_dir: str, agent_name: str) -> None:
        """Initialize cache at cache_dir/agent_name.json."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / f"{agent_name}.json"

    @classmethod
    def for_agent(cls, thread_id: str, agent_name: str) -> AgentMessageCache:
        """Convenience constructor: cache rooted at .pipeline_runs/<thread_id>/.

        Sugar over ``AgentMessageCache(f".pipeline_runs/{thread_id}/", agent_name)``
        so call sites don't have to hardcode the persistence-directory prefix.
        Per-agent and per-thread isolation come from the directory + filename
        layout — separate threads write under separate sub-dirs, separate
        agents within a thread write under separate filenames.

        PRD §6.9.T2 + OQ-NEW-71.
        """
        return cls(cache_dir=f".pipeline_runs/{thread_id}/", agent_name=agent_name)

    def save(self, messages_json: bytes) -> None:
        """Save message history from result.all_messages_json()."""
        self.cache_path.write_bytes(messages_json)
        logger.debug("Cache saved: %s (%d bytes)", self.cache_path, len(messages_json))

    def load(self) -> list[ModelMessage] | None:
        """Load cached messages, returning deserialized ModelMessage list."""
        if not self.cache_path.exists():
            return None
        try:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            raw = self.cache_path.read_bytes()
            messages = ModelMessagesTypeAdapter.validate_json(raw)
            logger.info("Cache loaded: %s (%d messages)", self.cache_path, len(messages))
            return messages
        except Exception:
            logger.warning("Corrupt cache at %s — ignoring", self.cache_path, exc_info=True)
            return None

    def clear(self) -> None:
        """Clear cache file."""
        if self.cache_path.exists():
            self.cache_path.unlink()
            logger.debug("Cache cleared: %s", self.cache_path)

    def exists(self) -> bool:
        """Check if a cache exists."""
        return self.cache_path.exists()
