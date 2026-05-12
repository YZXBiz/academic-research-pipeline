"""Tests for logfire.span enrichment of the 5 new event types (PRD §6.13.T1).

Each of recovery_event, doi_gate_failure, cascade_verdict, novelty_gate_verdict,
and ethics_checklist_result emits a Logfire span via logfire.span() alongside
the events.jsonl write. Per PRD AP37: same error_code and ts (within ±1s) on
both records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from academic_pipeline.runtime.events import EventLogger


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_span() -> MagicMock:
    """Replace logfire.span with a MagicMock so we can inspect calls."""
    return MagicMock()


def test_recovery_event_emits_logfire_span(tmp_path: Path, mock_span: MagicMock) -> None:
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "recovery_event",
            layer=4,
            action="kill",
            reason="stale",
            strike=1,
            error_code="REC004",
        )
    assert mock_span.called
    args, kwargs = mock_span.call_args
    # span name should reflect the event type
    assert "recovery_event" in args[0] if args else "recovery_event" in kwargs.get("msg_template", "")


def test_doi_gate_failure_emits_logfire_span(tmp_path: Path, mock_span: MagicMock) -> None:
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "doi_gate_failure",
            doi="10.1/bad",
            crossref_status=404,
            blocking=True,
            error_code="REN001",
        )
    assert mock_span.called


def test_cascade_verdict_emits_logfire_span(tmp_path: Path, mock_span: MagicMock) -> None:
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "cascade_verdict",
            stage="A",
            verdict="pass",
            score=0.9,
            reason="ok",
            short_circuited=False,
        )
    assert mock_span.called


def test_novelty_gate_verdict_emits_logfire_span(tmp_path: Path, mock_span: MagicMock) -> None:
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "novelty_gate_verdict",
            verdict="partial",
            max_similarity=0.83,
            tau_warn=0.78,
            tau_block=0.92,
            neighbors=[],
        )
    assert mock_span.called


def test_ethics_checklist_result_emits_logfire_span(tmp_path: Path, mock_span: MagicMock) -> None:
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "ethics_checklist_result",
            items_total=12,
            items_pass=12,
            items_fail=0,
            items_na=0,
            fails=[],
            blocking=False,
        )
    assert mock_span.called


def test_pipeline_start_does_not_emit_span(tmp_path: Path, mock_span: MagicMock) -> None:
    """Span enrichment is only for the 5 new event types — not the legacy ones
    that already get instrumented via the global httpx + per-agent paths."""
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "pipeline_start",
            run_id="r",
            topic="t",
            resumed=False,
        )
    assert not mock_span.called


def test_span_carries_same_error_code_as_events_jsonl_record(
    tmp_path: Path,
    mock_span: MagicMock,
) -> None:
    """PRD AP37 — span and events.jsonl record share the same error_code so
    operators can correlate Logfire searches against the on-disk event log."""
    logger = EventLogger(tmp_path)
    with patch("logfire.span", mock_span):
        logger.emit_sync(
            "cascade_verdict",
            stage="B",
            verdict="fail",
            score=0.42,
            reason="missing tokens",
            short_circuited=True,
            error_code="CAS001",
        )
    _, kwargs = mock_span.call_args
    # All payload fields should be passed as span attributes — error_code must
    # be discoverable so AP37 correlation works.
    assert kwargs.get("error_code") == "CAS001" or "CAS001" in str(kwargs)


def test_span_emission_does_not_raise_when_logfire_unavailable(
    tmp_path: Path,
) -> None:
    """Observability must never block the write path. If logfire is missing or
    fails, the events.jsonl record still lands."""
    logger = EventLogger(tmp_path)
    with patch.dict("sys.modules", {"logfire": None}):
        # Should not raise
        logger.emit_sync(
            "recovery_event",
            layer=4,
            action="kill",
            reason="stale",
            strike=1,
            error_code="REC004",
        )
    # The events.jsonl record landed — first line is schema_version marker,
    # second is the recovery_event.
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert "recovery_event" in lines[1]
