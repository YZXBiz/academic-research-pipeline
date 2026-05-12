"""Tests for the PRD §6.9.T1 schema-version gate on PipelineState resume.

Each test exercises the version-mismatch path through SqliteStatePersistence's
pipeline-state load. Pre-v2.5.0 state files have no `_schema_version` field
and must raise PRS001 IncompatibleStateError; in-version files load cleanly.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path


def _make_persistence(db_path: Path):
    from academic_pipeline.persistence import SqliteStatePersistence

    # State + run-end types are unused for the pipeline-state path; use object.
    return SqliteStatePersistence[object, object](db_path=db_path, run_id="t-schema")


def test_pipeline_state_has_schema_version_field():
    """PipelineState carries a current `_schema_version` field for v2.5.0."""
    from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION, PipelineState

    state = PipelineState()
    assert hasattr(state, "_schema_version")
    assert state._schema_version == PIPELINE_STATE_SCHEMA_VERSION
    assert PIPELINE_STATE_SCHEMA_VERSION >= 1


def test_load_rejects_missing_schema_version_with_prs001(tmp_path: Path):
    """A pre-v2.5.0 state file (no `_schema_version` key) raises PRS001."""
    from academic_pipeline.persistence import SqliteStatePersistence
    from academic_pipeline.persistence_errors import IncompatibleStateError

    db = tmp_path / "p.sqlite"
    persistence = SqliteStatePersistence[object, object](db_path=db, run_id="t-old")

    # Save a state JSON the *legacy* way — no schema_version key.
    legacy = json.dumps({"topic": "x", "run_id": "t-old"})
    asyncio.run(persistence.save_pipeline_state("t-old", legacy))

    with pytest.raises(IncompatibleStateError) as exc_info:
        asyncio.run(persistence.load_pipeline_state("t-old"))
    assert exc_info.value.error_code == "PRS001"


def test_load_rejects_mismatched_schema_version_with_prs001(tmp_path: Path):
    """A state file from a different schema version raises PRS001."""
    from academic_pipeline.persistence import SqliteStatePersistence
    from academic_pipeline.persistence_errors import IncompatibleStateError
    from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

    db = tmp_path / "p.sqlite"
    persistence = SqliteStatePersistence[object, object](db_path=db, run_id="t-mismatch")

    bad = json.dumps(
        {
            "topic": "x",
            "run_id": "t-mismatch",
            "_schema_version": PIPELINE_STATE_SCHEMA_VERSION + 99,
        }
    )
    asyncio.run(persistence.save_pipeline_state("t-mismatch", bad))

    with pytest.raises(IncompatibleStateError) as exc_info:
        asyncio.run(persistence.load_pipeline_state("t-mismatch"))
    assert exc_info.value.error_code == "PRS001"
    assert "schema" in str(exc_info.value).lower()


def test_load_returns_state_for_matching_schema_version(tmp_path: Path):
    """A state file at the current schema version round-trips cleanly."""
    from academic_pipeline.persistence import SqliteStatePersistence
    from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

    db = tmp_path / "p.sqlite"
    persistence = SqliteStatePersistence[object, object](db_path=db, run_id="t-ok")

    good = json.dumps(
        {
            "topic": "x",
            "run_id": "t-ok",
            "_schema_version": PIPELINE_STATE_SCHEMA_VERSION,
        }
    )
    asyncio.run(persistence.save_pipeline_state("t-ok", good))

    out = asyncio.run(persistence.load_pipeline_state("t-ok"))
    assert out == good


def test_load_returns_none_when_run_id_absent(tmp_path: Path):
    """No row for the run_id ⇒ load returns None (no exception)."""
    db = tmp_path / "p.sqlite"
    persistence = _make_persistence(db)
    assert asyncio.run(persistence.load_pipeline_state("never-saved")) is None
