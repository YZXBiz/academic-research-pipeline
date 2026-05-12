"""Tests for the EventLogger append-only event writer."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from academic_pipeline.runtime.events import EventLogger


if TYPE_CHECKING:
    from pathlib import Path


def test_emit_sync_appends_jsonl_with_ts_and_type(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    logger.emit_sync("pipeline_start", run_id="r1", topic="t")
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    # First line is the schema_version marker (PRD §6.8.T3); event follows.
    assert len(lines) == 2
    record = json.loads(lines[1])
    assert record["type"] == "pipeline_start"
    assert record["run_id"] == "r1"
    assert record["topic"] == "t"
    assert isinstance(record["ts"], float)


def test_emit_sync_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    logger = EventLogger(nested)
    logger.emit_sync("test")
    assert (nested / "events.jsonl").exists()


def test_emit_sync_appends_not_overwrites(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    logger.emit_sync("first")
    logger.emit_sync("second")
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    # First line is the schema_version marker (PRD §6.8.T3); events follow.
    assert len(lines) == 3
    assert json.loads(lines[1])["type"] == "first"
    assert json.loads(lines[2])["type"] == "second"


def test_emit_sync_handles_unicode(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    logger.emit_sync("pipeline_start", topic="Café résumé 中文 🎉")
    # First line is the schema_version marker (PRD §6.8.T3); event follows.
    record = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[1])
    assert record["topic"] == "Café résumé 中文 🎉"


def test_emit_sync_calls_fsync(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    with patch("academic_pipeline.runtime.events.os.fsync") as mock_fsync:
        logger.emit_sync("test")
    mock_fsync.assert_called_once()


@pytest.mark.asyncio()
async def test_emit_async_writes_same_record_as_sync(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    await logger.emit("pipeline_start", run_id="r1")
    # First line is the schema_version marker (PRD §6.8.T3); event follows.
    record = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[1])
    assert record["type"] == "pipeline_start"
    assert record["run_id"] == "r1"
    assert isinstance(record["ts"], float)


@pytest.mark.asyncio()
async def test_emit_async_does_not_block_event_loop(tmp_path: Path) -> None:
    """During an async emit, other tasks on the loop must continue running."""
    logger = EventLogger(tmp_path)
    counter = 0

    async def tick() -> None:
        nonlocal counter
        for _ in range(50):
            counter += 1
            await asyncio.sleep(0.001)

    async def slow_emit() -> None:
        # Patch fsync to take a noticeable amount of wall time
        from academic_pipeline.runtime import events as events_mod

        orig_fsync = events_mod.os.fsync

        def slow_fsync(fd: int) -> None:
            time.sleep(0.05)
            orig_fsync(fd)

        events_mod.os.fsync = slow_fsync  # type: ignore[assignment]
        try:
            await logger.emit("test")
        finally:
            events_mod.os.fsync = orig_fsync  # type: ignore[assignment]

    await asyncio.gather(tick(), slow_emit())
    # If emit blocked the loop, counter would be < 50.
    assert counter == 50
