"""SQLite-backed state persistence for pydantic-graph runs."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any

from pydantic_graph import _utils as _graph_utils
from pydantic_graph import exceptions
from pydantic_graph.persistence import (
    BaseStatePersistence,
    EndSnapshot,
    NodeSnapshot,
    RunEndT,
    Snapshot,
    StateT,
    _utils,
    build_snapshot_list_type_adapter,
)


if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import pydantic
    from pydantic_graph.nodes import BaseNode, End
    from pydantic_graph.persistence import SnapshotStatus

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    data_json TEXT NOT NULL,
    duration REAL,
    start_ts TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_run ON snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_sid ON snapshots(run_id, snapshot_id);

CREATE TABLE IF NOT EXISTS pipeline_state (
    run_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class SqliteStatePersistence(BaseStatePersistence[StateT, RunEndT]):
    """SQLite-backed state persistence for pydantic-graph runs."""

    db_path: Path
    run_id: str

    _snapshots_type_adapter: pydantic.TypeAdapter[list[Snapshot[StateT, RunEndT]]] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    # ---- abstract method implementations ----

    async def snapshot_node(self, state: StateT, next_node: BaseNode[StateT, Any, RunEndT]) -> None:
        """Store a NodeSnapshot for the given state and next node."""
        snapshot = NodeSnapshot(state=state, node=next_node)
        await _graph_utils.run_in_executor(self._insert_snapshot, snapshot)

    async def snapshot_node_if_new(
        self, snapshot_id: str, state: StateT, next_node: BaseNode[StateT, Any, RunEndT]
    ) -> None:
        """Store a NodeSnapshot only if no snapshot with this id exists yet."""
        snapshots = await self.load_all()
        if not any(s.id == snapshot_id for s in snapshots):
            await self.snapshot_node(state, next_node)

    async def snapshot_end(self, state: StateT, end: End[RunEndT]) -> None:
        """Store an EndSnapshot for the given state and end result."""
        snapshot = EndSnapshot(state=state, result=end)
        await _graph_utils.run_in_executor(self._insert_snapshot, snapshot)

    @asynccontextmanager
    async def record_run(self, snapshot_id: str) -> AsyncIterator[None]:
        """Record execution of a snapshot, setting status to running then success/error."""
        snapshots = await self.load_all()
        try:
            snapshot = next(s for s in snapshots if s.id == snapshot_id)
        except StopIteration as e:
            raise LookupError(f"No snapshot found with id={snapshot_id!r}") from e

        assert isinstance(snapshot, NodeSnapshot), "Only NodeSnapshot can be recorded"
        exceptions.GraphNodeStatusError.check(snapshot.status)

        await _graph_utils.run_in_executor(
            self._update_status_sync, snapshot_id, "running", None, _utils.now_utc().isoformat()
        )

        start = perf_counter()
        try:
            yield
        except Exception:
            duration = perf_counter() - start
            await _graph_utils.run_in_executor(self._update_status_sync, snapshot_id, "error", duration, None)
            raise
        else:
            duration = perf_counter() - start
            await _graph_utils.run_in_executor(self._update_status_sync, snapshot_id, "success", duration, None)

    async def load_next(self) -> NodeSnapshot[StateT, RunEndT] | None:
        """Return the first 'created' snapshot and set its status to 'pending'."""
        snapshots = await self.load_all()
        for snap in snapshots:
            if isinstance(snap, NodeSnapshot) and snap.status == "created":
                await _graph_utils.run_in_executor(self._update_status_sync, snap.id, "pending", None, None)
                snap.status = "pending"
                return snap
        return None

    async def load_all(self) -> list[Snapshot[StateT, RunEndT]]:
        """Load all snapshots for this run_id."""
        return await _graph_utils.run_in_executor(self._load_all_sync)

    def should_set_types(self) -> bool:
        """Return True when the TypeAdapter has not been configured yet."""
        return self._snapshots_type_adapter is None

    def set_types(self, state_type: type[StateT], run_end_type: type[RunEndT]) -> None:
        """Build and store a TypeAdapter for snapshot serialization."""
        self._snapshots_type_adapter = build_snapshot_list_type_adapter(state_type, run_end_type)

    # ---- pipeline-state helpers ----

    async def save_pipeline_state(self, run_id: str, state_json: str) -> None:
        """Upsert pipeline state JSON for the given run_id."""
        await _graph_utils.run_in_executor(self._save_pipeline_state_sync, run_id, state_json)

    async def load_pipeline_state(self, run_id: str) -> str | None:
        """Load pipeline state JSON for the given run_id, or None if missing.

        Raises IncompatibleStateError (PRS001) if the persisted JSON's
        ``_schema_version`` is missing or does not match
        ``PIPELINE_STATE_SCHEMA_VERSION``. PRD §6.9.T1.
        """
        raw = await _graph_utils.run_in_executor(self._load_pipeline_state_sync, run_id)
        if raw is None:
            return None
        self._verify_schema_version(raw, run_id)
        return raw

    @staticmethod
    def _verify_schema_version(raw_json: str, run_id: str) -> None:
        """Reject state JSON whose `_schema_version` doesn't match this build."""
        import json as _json

        from academic_pipeline.persistence_errors import IncompatibleStateError
        from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

        try:
            payload = _json.loads(raw_json)
        except _json.JSONDecodeError:
            # Corrupt JSON is a separate failure class; let the caller
            # surface it. The schema-version gate is only for well-formed
            # payloads.
            return

        found = payload.get("_schema_version") if isinstance(payload, dict) else None
        if found != PIPELINE_STATE_SCHEMA_VERSION:
            raise IncompatibleStateError(
                f"State for run_id={run_id!r} has _schema_version={found!r}, "
                f"expected {PIPELINE_STATE_SCHEMA_VERSION}. "
                "Run `python -m academic_pipeline cleanup-state --before 2.5.0 --confirm` "
                "to archive incompatible state files (see docs/architecture/recovery.md).",
                run_id=run_id,
                found_version=found if isinstance(found, int) else None,
                expected_version=PIPELINE_STATE_SCHEMA_VERSION,
            )

    async def can_resume(self) -> bool:
        """Return True if any snapshots exist for this run_id."""
        return await _graph_utils.run_in_executor(self._can_resume_sync)

    async def reset_crashed_snapshots(self) -> None:
        """Reset 'running' and 'error' snapshots back to 'created'."""
        await _graph_utils.run_in_executor(self._reset_crashed_sync)

    # ---- sync helpers ----

    def _insert_snapshot(self, snapshot: Snapshot[StateT, RunEndT]) -> None:
        assert self._snapshots_type_adapter is not None, "snapshots type adapter must be set"
        json_bytes = self._snapshots_type_adapter.dump_json([snapshot])
        json_str = json_bytes.decode()
        # Strip the outer [] to get the single object JSON
        inner = json_str.strip()
        inner = inner.removeprefix("[")
        inner = inner.removesuffix("]")
        inner = inner.strip()

        kind = "end" if isinstance(snapshot, EndSnapshot) else "node"
        status = snapshot.status if isinstance(snapshot, NodeSnapshot) else "created"
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO snapshots (run_id, snapshot_id, kind, status, data_json) VALUES (?, ?, ?, ?, ?)",
                (self.run_id, snapshot.id, kind, status, inner),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_all_sync(self) -> list[Snapshot[StateT, RunEndT]]:
        assert self._snapshots_type_adapter is not None, "snapshots type adapter must be set"
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT data_json FROM snapshots WHERE run_id = ? ORDER BY id",
                (self.run_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        combined = "[" + ",".join(row[0] for row in rows) + "]"
        return self._snapshots_type_adapter.validate_json(combined.encode())

    def _update_status_sync(
        self,
        snapshot_id: str,
        status: SnapshotStatus,
        duration: float | None,
        start_ts: str | None,
    ) -> None:
        """Update a snapshot's status/duration/start_ts in the DB, then rewrite data_json to match."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            if start_ts is not None:
                conn.execute(
                    "UPDATE snapshots SET status = ?, start_ts = ? WHERE run_id = ? AND snapshot_id = ?",
                    (status, start_ts, self.run_id, snapshot_id),
                )
            elif duration is not None:
                conn.execute(
                    "UPDATE snapshots SET status = ?, duration = ? WHERE run_id = ? AND snapshot_id = ?",
                    (status, duration, self.run_id, snapshot_id),
                )
            else:
                conn.execute(
                    "UPDATE snapshots SET status = ? WHERE run_id = ? AND snapshot_id = ?",
                    (status, self.run_id, snapshot_id),
                )
            conn.commit()
        finally:
            conn.close()

        self._rewrite_data_json(snapshot_id)

    def _rewrite_data_json(self, snapshot_id: str) -> None:
        """Reload all snapshots, apply current DB metadata, and rewrite data_json for one row."""
        assert self._snapshots_type_adapter is not None
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT data_json FROM snapshots WHERE run_id = ? ORDER BY id",
                (self.run_id,),
            ).fetchall()
            if not rows:
                return

            combined = "[" + ",".join(row[0] for row in rows) + "]"
            snapshots = self._snapshots_type_adapter.validate_json(combined.encode())

            meta_row = conn.execute(
                "SELECT status, duration, start_ts FROM snapshots WHERE run_id = ? AND snapshot_id = ?",
                (self.run_id, snapshot_id),
            ).fetchone()
            if meta_row is None:
                return

            db_status, db_duration, db_start_ts = meta_row

            for snap in snapshots:
                if snap.id == snapshot_id:
                    if isinstance(snap, NodeSnapshot):
                        snap.status = db_status
                        snap.duration = db_duration
                        if db_start_ts is not None:
                            snap.start_ts = datetime.fromisoformat(db_start_ts).replace(tzinfo=UTC)
                    break

            updated_json_bytes = self._snapshots_type_adapter.dump_json(snapshots)
            parsed = json.loads(updated_json_bytes.decode())
            for item in parsed:
                if item.get("id", "") == snapshot_id:
                    conn.execute(
                        "UPDATE snapshots SET data_json = ? WHERE run_id = ? AND snapshot_id = ?",
                        (json.dumps(item), self.run_id, snapshot_id),
                    )
                    conn.commit()
                    break
        finally:
            conn.close()

    def _save_pipeline_state_sync(self, run_id: str, state_json: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO pipeline_state (run_id, state_json) VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET state_json = excluded.state_json, "
                "updated_at = datetime('now')",
                (run_id, state_json),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_pipeline_state_sync(self, run_id: str) -> str | None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT state_json FROM pipeline_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _can_resume_sync(self) -> bool:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            return bool(row and row[0] > 0)
        finally:
            conn.close()

    def _reset_crashed_sync(self) -> None:
        """Reset 'running' and 'error' snapshots back to 'created'."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT snapshot_id FROM snapshots WHERE run_id = ? AND status IN ('running', 'error')",
                (self.run_id,),
            ).fetchall()

            if not rows:
                return

            conn.execute(
                "UPDATE snapshots SET status = 'created', duration = NULL, start_ts = NULL "
                "WHERE run_id = ? AND status IN ('running', 'error')",
                (self.run_id,),
            )
            conn.commit()

            if self._snapshots_type_adapter is not None:
                for (sid,) in rows:
                    self._rewrite_data_json(sid)
            else:
                # TypeAdapter not configured yet (called before
                # graph.iter_from_persistence sets types). Patch data_json
                # directly so load_next() sees status='created'.
                for (sid,) in rows:
                    row = conn.execute(
                        "SELECT data_json FROM snapshots WHERE run_id = ? AND snapshot_id = ?",
                        (self.run_id, sid),
                    ).fetchone()
                    if row:
                        data = json.loads(row[0])
                        data["status"] = "created"
                        data.pop("duration", None)
                        data.pop("start_ts", None)
                        conn.execute(
                            "UPDATE snapshots SET data_json = ? WHERE run_id = ? AND snapshot_id = ?",
                            (json.dumps(data), self.run_id, sid),
                        )
                conn.commit()
        finally:
            conn.close()
