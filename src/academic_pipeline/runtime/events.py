"""Append-only structured event log for pipeline runs.

Includes typed pydantic models for the 5 new event types added in v2.5.0
per PRD §6.8.T1. The models declare wire shapes for `recovery_event`,
`doi_gate_failure`, `cascade_verdict`, `novelty_gate_verdict`, and
`ethics_checklist_result`. The `ts` and `type` fields are stamped by
`EventLogger.emit_sync` / `EventLogger.emit` and are NOT part of the
typed models themselves.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


if TYPE_CHECKING:
    from pathlib import Path


# events.jsonl schema version. First line of every events.jsonl is
# {"event_type": "schema_version", "version": SCHEMA_VERSION}. Renderer
# rejects mismatched majors with DSH001 SchemaVersionMismatch (PRD §6.8.T3).
SCHEMA_VERSION = "2.5.0"


class RecoveryEvent(BaseModel):
    """Recovery-layer action emitted alongside watchdog_* events.

    Per PRD §6.6.T2 + §18. Layers: 1=TCP keepalive, 2=bounded_run,
    3=heartbeat thread, 4=watchdog supervisor.
    """

    model_config = ConfigDict(frozen=True)

    layer: int = Field(ge=1, le=4)
    action: Literal["kill", "resume", "abort"]
    reason: str
    strike: int = Field(ge=1, le=3)
    error_code: str


class DoiGateFailureEvent(BaseModel):
    """DOI verification failure during the rendering build gate.

    Per PRD §6.7.T2 + §18. `blocking=False` only when the operator passed
    `--allow-unverified-dois`.
    """

    model_config = ConfigDict(frozen=True)

    doi: str
    crossref_status: int
    blocking: bool
    error_code: str


class CascadeVerdictEvent(BaseModel):
    """Cascaded review verdict per stage A/B/C.

    Per PRD §6.4 + §18. `error_code` is omitted when verdict=="pass".
    """

    model_config = ConfigDict(frozen=True)

    stage: Literal["A", "B", "C"]
    verdict: Literal["pass", "fail"]
    score: float
    reason: str
    short_circuited: bool
    error_code: str | None = None


class NoveltyNeighbor(BaseModel):
    """One Semantic Scholar neighbor returned by the novelty gate."""

    model_config = ConfigDict(frozen=True)

    title: str
    doi: str
    semantic_scholar_id: str
    cosine_similarity: float
    abstract_excerpt: str


class NoveltyGateVerdictEvent(BaseModel):
    """Novelty gate verdict.

    Per PRD §6.1 (Spec 3) + §18. `differentiation_paragraph` and
    `error_code` are populated only when verdict in {"partial","redundant"}.
    """

    model_config = ConfigDict(frozen=True)

    verdict: Literal["novel", "partial", "redundant"]
    max_similarity: float
    tau_warn: float
    tau_block: float
    neighbors: list[NoveltyNeighbor]
    differentiation_paragraph: str | None = None
    error_code: str | None = None


class EthicsChecklistResultEvent(BaseModel):
    """PRISMA-trAIce ethics checklist outcome.

    Per PRD §6.5 (Spec 8) + §18. `error_code` is omitted when items_fail==0.
    """

    model_config = ConfigDict(frozen=True)

    items_total: int = Field(ge=0)
    items_pass: int = Field(ge=0)
    items_fail: int = Field(ge=0)
    items_na: int = Field(ge=0)
    fails: list[dict[str, str]]
    blocking: bool
    error_code: str | None = None


# Event types that get a parallel logfire.span() emission per PRD §6.13.T1.
# Pairs with the typed pydantic models defined above (added in §6.8.T1).
_SPAN_ENRICHED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "recovery_event",
        "doi_gate_failure",
        "cascade_verdict",
        "novelty_gate_verdict",
        "ethics_checklist_result",
    }
)


def _emit_event_span(event_type: str, record: dict[str, Any]) -> None:
    """Emit a Logfire span carrying the same payload as the events.jsonl record.

    Per PRD §6.13.T1 + AP37: same error_code and ts (within ±1s) on both records
    so operators can correlate Logfire searches against the on-disk event log.
    Failures are silenced — observability never blocks the write path.
    """
    try:
        import logfire

        logfire.span(f"event:{event_type}", **record)
    except Exception:
        # Logfire absent / unconfigured / SDK mismatch — events.jsonl record
        # already landed in the caller, so silently skip the span.
        pass


class EventLogger:
    """Append structured events to a per-run JSONL file.

    Append-only, fsynced per record. Single-writer (the pipeline). Readers must
    tolerate a malformed line in case of crash mid-write.
    """

    def __init__(self, run_dir: Path) -> None:
        """Open (or create) `run_dir/events.jsonl` for append.

        On first creation only, prepends a schema_version marker line so
        renderers can detect incompatible majors (PRD §6.8.T3).
        """
        self._path = run_dir / "events.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            marker = {"event_type": "schema_version", "version": SCHEMA_VERSION}
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(marker, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

    @property
    def path(self) -> Path:
        """Absolute path of the JSONL file this logger writes to."""
        return self._path

    def emit_sync(self, event_type: str, **fields: Any) -> None:
        """Blocking emit. Use from sync code (tests, CLI)."""
        record = {"ts": time.time(), "type": event_type, **fields}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Span enrichment for the 5 new event types per PRD §6.13.T1. Same
        # error_code + ts (within ±1s) as the events.jsonl record per AP37 —
        # both writes happen here, so the timestamps coincide naturally.
        if event_type in _SPAN_ENRICHED_EVENT_TYPES:
            _emit_event_span(event_type, record)

    async def emit(self, event_type: str, **fields: Any) -> None:
        """Async emit.

        Offloads the blocking write+fsync to a worker thread so the asyncio
        event loop running pydantic-graph (and any concurrent agents) is
        never blocked.
        """
        await asyncio.to_thread(self.emit_sync, event_type, **fields)
