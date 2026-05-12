"""Tests for traceability_error_event payload helper (PRD §6.10.T6)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from academic_pipeline.runtime.events import EventLogger
from academic_pipeline.traceability.errors import (
    CopilotTimeout,
    DialogueExhaustion,
    NumericValidatorAbort,
    NumericValidatorRetry,
    StoreIntegrityError,
    SubstitutionFailure,
    traceability_error_event,
)


if TYPE_CHECKING:
    from pathlib import Path


def test_event_for_numeric_validator_retry_carries_trc001() -> None:
    err = NumericValidatorRetry(
        "hedge phrase near number",
        section_name="results",
        violation_type="hedge",
        offending_token="approximately",
    )
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC001"
    assert payload["section_name"] == "results"
    assert payload["violation_type"] == "hedge"


def test_event_for_numeric_validator_abort_carries_trc002() -> None:
    err = NumericValidatorAbort(
        "aborting phrase detected",
        section_name="discussion",
        aborting_phrase="[INSERT",
        position=42,
    )
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC002"
    assert payload["aborting_phrase"] == "[INSERT"
    assert payload["position"] == 42


def test_event_for_substitution_failure_carries_trc003() -> None:
    err = SubstitutionFailure(
        "unresolved label",
        label="missing_x",
        section_name="methods",
        store_label_count=12,
    )
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC003"
    assert payload["label"] == "missing_x"
    assert payload["store_label_count"] == 12


def test_event_for_store_integrity_error_carries_trc004() -> None:
    err = StoreIntegrityError(
        "duplicate label",
        invariant_name="unique_label",
        offending_label="dup_a",
    )
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC004"
    assert payload["invariant_name"] == "unique_label"
    assert payload["offending_label"] == "dup_a"


def test_event_for_copilot_timeout_carries_trc005() -> None:
    err = CopilotTimeout("stdin timed out", checkpoint_name="hitl-1", timeout_s=60)
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC005"
    assert payload["checkpoint_name"] == "hitl-1"
    assert payload["timeout_s"] == 60


def test_event_for_dialogue_exhaustion_carries_trc006() -> None:
    err = DialogueExhaustion(
        "max turns hit",
        section_name="introduction",
        turn_count=5,
        last_review_excerpt="still needs more depth",
    )
    payload = traceability_error_event(err)
    assert payload["error_code"] == "TRC006"
    assert payload["turn_count"] == 5
    assert payload["section_name"] == "introduction"


def test_event_payload_always_includes_message() -> None:
    err = SubstitutionFailure("the readable text", label="x")
    payload = traceability_error_event(err)
    assert payload["message"] == "the readable text"


def test_event_logger_round_trip_writes_jsonl_line(tmp_path: Path) -> None:
    """End-to-end: helper payload, when emitted by EventLogger, produces a
    valid jsonl record carrying the error code + context fields."""
    logger = EventLogger(tmp_path)
    err = SubstitutionFailure("unresolved", label="lbl", store_label_count=3)
    payload = traceability_error_event(err)
    logger.emit_sync("traceability_error", **payload)
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    # First line is the schema_version marker; the error event is the second.
    record = json.loads(lines[1])
    assert record["type"] == "traceability_error"
    assert record["error_code"] == "TRC003"
    assert record["label"] == "lbl"
    assert record["store_label_count"] == 3
