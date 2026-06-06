"""Tests for deterministic temporal verification."""

from __future__ import annotations

from datetime import UTC, datetime

from academic_pipeline.models.citation_verification import CitationVerification, LookupVerified
from academic_pipeline.models.temporal_verification import TemporalKind, verify_temporal


_NOW = datetime(2026, 6, 5, tzinfo=UTC)


def _cv(source_id: str, year: int | None) -> CitationVerification:
    return CitationVerification(
        source_id=source_id,
        lookup_verified=LookupVerified.TRUE,
        published_year=year,
        verification_timestamp=_NOW,
    )


def test_flags_future_dated_citation() -> None:
    report = verify_temporal([_cv("s1", 2027), _cv("s2", 2020)], reference_year=2025)
    assert [f.source_id for f in report.findings] == ["s1"]
    assert report.findings[0].kind is TemporalKind.FUTURE_AS_PAST
    assert report.findings[0].cited_year == 2027
    assert report.findings[0].reference_year == 2025


def test_same_year_is_ok() -> None:
    assert verify_temporal([_cv("s1", 2025)], reference_year=2025).findings == []


def test_none_year_is_skipped() -> None:
    assert verify_temporal([_cv("s1", None)], reference_year=2025).findings == []


def test_blocking_rows_and_summary() -> None:
    report = verify_temporal([_cv("s1", 2030)], reference_year=2025)
    assert len(report.blocking_rows) == 1
    assert "1 temporally-impossible" in report.summary
