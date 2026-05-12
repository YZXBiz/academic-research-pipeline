"""Typed exceptions for the persistence + agent-cache layer (PRS namespace).

Every persistence failure inherits from PersistenceError and carries a stable
error_code (PRS001-PRS099) for postmortem grep over events.jsonl. PRD §17.

Class names intentionally omit the "Error" suffix on the typed-failure
classes because the codes themselves (PRS00x) are the canonical identifiers.
N818 is silenced per-class.
"""

from __future__ import annotations


class PersistenceError(Exception):
    """Base for all persistence failures. Never raise directly."""

    error_code: str = "PRS000"


class IncompatibleStateError(PersistenceError):
    """State file's `_schema_version` does not match the current schema.

    Raised by SqliteStatePersistence.load_pipeline_state when:
      - the persisted JSON has no `_schema_version` key (pre-v2.5.0), OR
      - the persisted version differs from PIPELINE_STATE_SCHEMA_VERSION.

    Operators clean up incompatible state files via `tools/cleanup_state.py`
    (PRD §6.9.T5). PRD §17 PRS001.
    """

    error_code = "PRS001"

    def __init__(
        self,
        message: str,
        *,
        run_id: str | None = None,
        found_version: int | None = None,
        expected_version: int | None = None,
    ) -> None:
        """Store the run_id and version info for postmortem inspection."""
        super().__init__(message)
        self.run_id = run_id
        self.found_version = found_version
        self.expected_version = expected_version
