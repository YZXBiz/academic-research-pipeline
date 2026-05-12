"""Pipeline event types for the run_stream() async generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    STAGE_CHANGE = "stage_change"
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    MESSAGE = "message"
    ARTIFACT_READY = "artifact_ready"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class PipelineEvent:
    """A single event emitted during pipeline execution."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
