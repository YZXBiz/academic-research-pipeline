"""Tests for events.jsonl schema_version first-line marker (PRD §6.8.T3)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from academic_pipeline.runtime.dashboard import (
    SchemaVersionMismatch,
    validate_schema_version,
)
from academic_pipeline.runtime.events import SCHEMA_VERSION, EventLogger


if TYPE_CHECKING:
    from pathlib import Path


def test_schema_version_constant_matches_project_version() -> None:
    assert SCHEMA_VERSION == "2.5.0"


def test_event_logger_writes_schema_version_as_first_line(tmp_path: Path) -> None:
    EventLogger(tmp_path)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "schema_version"
    assert record["version"] == SCHEMA_VERSION


def test_event_logger_emit_appends_after_marker(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    logger.emit_sync("pipeline_start", run_id="r1", topic="t")
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    marker = json.loads(lines[0])
    assert marker["event_type"] == "schema_version"
    record = json.loads(lines[1])
    assert record["type"] == "pipeline_start"


def test_event_logger_does_not_emit_marker_when_file_already_exists(tmp_path: Path) -> None:
    """A second EventLogger pointed at the same dir must NOT prepend a marker."""
    EventLogger(tmp_path)
    EventLogger(tmp_path)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    # only the original single marker — no duplicate
    assert len(lines) == 1


def test_validate_schema_version_passes_for_matching_major(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(json.dumps({"event_type": "schema_version", "version": "2.5.0"}) + "\n")
    validate_schema_version(p)  # must not raise


def test_validate_schema_version_passes_when_minor_differs(tmp_path: Path) -> None:
    """Mismatched minors are accepted; only majors matter."""
    p = tmp_path / "events.jsonl"
    p.write_text(json.dumps({"event_type": "schema_version", "version": "2.99.99"}) + "\n")
    validate_schema_version(p)  # major == 2 → ok


def test_validate_schema_version_rejects_mismatched_major(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(json.dumps({"event_type": "schema_version", "version": "3.0.0"}) + "\n")
    with pytest.raises(SchemaVersionMismatch) as exc_info:
        validate_schema_version(p)
    assert "DSH001" in str(exc_info.value)
    assert "3.0.0" in str(exc_info.value)


def test_validate_schema_version_rejects_missing_marker(tmp_path: Path) -> None:
    """Pre-v2.5.0 events.jsonl lacks the marker; renderer rejects (PRD R21)."""
    p = tmp_path / "events.jsonl"
    p.write_text(json.dumps({"ts": 1.0, "type": "pipeline_start"}) + "\n")
    with pytest.raises(SchemaVersionMismatch) as exc_info:
        validate_schema_version(p)
    assert "DSH001" in str(exc_info.value)


def test_validate_schema_version_rejects_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text("")
    with pytest.raises(SchemaVersionMismatch):
        validate_schema_version(p)


def test_validate_schema_version_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SchemaVersionMismatch):
        validate_schema_version(tmp_path / "nonexistent.jsonl")


def test_validate_schema_version_rejects_malformed_first_line(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text("this is not json\n")
    with pytest.raises(SchemaVersionMismatch):
        validate_schema_version(p)
