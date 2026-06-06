"""Tests for CitationExistenceReport aggregation + extract_cited_work."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from academic_pipeline.models.citation_verification import (
    CitationExistenceReport,
    CitationVerification,
    LookupVerified,
)
from academic_pipeline.tools.bibliography.citation_verifier import extract_cited_work


if TYPE_CHECKING:
    from academic_pipeline.models.shared import Source


_NOW = datetime(2026, 6, 5, tzinfo=UTC)


def _cv(source_id: str, lv: LookupVerified, *, retracted: bool = False) -> CitationVerification:
    return CitationVerification(
        source_id=source_id,
        lookup_verified=lv,
        retracted=retracted,
        verification_timestamp=_NOW,
    )


class TestCitationExistenceReport:
    def test_by_status_counts_all_keys(self) -> None:
        report = CitationExistenceReport(
            verifications=[
                _cv("s1", LookupVerified.TRUE),
                _cv("s2", LookupVerified.FALSE),
                _cv("s3", LookupVerified.UNRESOLVABLE),
                _cv("s4", LookupVerified.TRUE),
            ]
        )
        assert report.by_status[LookupVerified.TRUE] == 2
        assert report.by_status[LookupVerified.FALSE] == 1
        assert report.by_status[LookupVerified.CONFLICT] == 0  # every key present

    def test_false_and_retracted_rows(self) -> None:
        report = CitationExistenceReport(
            verifications=[
                _cv("s1", LookupVerified.FALSE),
                _cv("s2", LookupVerified.TRUE, retracted=True),
                _cv("s3", LookupVerified.TRUE),
            ]
        )
        assert [v.source_id for v in report.false_rows] == ["s1"]
        assert [v.source_id for v in report.retracted_rows] == ["s2"]

    def test_blocking_rows_union_deduped(self) -> None:
        report = CitationExistenceReport(
            verifications=[
                _cv("s1", LookupVerified.FALSE),
                _cv("s2", LookupVerified.TRUE, retracted=True),
            ]
        )
        assert {v.source_id for v in report.blocking_rows} == {"s1", "s2"}

    def test_advisory_summary_is_never_bare_pass(self) -> None:
        report = CitationExistenceReport(verifications=[_cv("s1", LookupVerified.TRUE)])
        summary = report.advisory_summary
        assert "verified" in summary
        assert summary.strip().upper() != "PASS"

    def test_empty_report(self) -> None:
        report = CitationExistenceReport()
        assert report.blocking_rows == []
        assert report.by_status[LookupVerified.TRUE] == 0


class TestExtractCitedWork:
    def test_maps_core_fields(self) -> None:
        src = SimpleNamespace(id="s007", title="A Paper", authors=["Davis", "Smith"], year=1989, doi="10.1/x")
        work = extract_cited_work(cast("Source", src))
        assert work.source_id == "s007"
        assert work.title == "A Paper"
        assert work.authors == ["Davis", "Smith"]
        assert work.year == 1989
        assert work.doi == "10.1/x"
        assert work.arxiv_id is None

    def test_derives_arxiv_id_from_arxiv_doi(self) -> None:
        src = SimpleNamespace(id="s1", title="T", authors=["A"], year=2023, doi="10.48550/arXiv.2301.00001")
        work = extract_cited_work(cast("Source", src))
        assert work.arxiv_id == "2301.00001"

    def test_no_doi(self) -> None:
        src = SimpleNamespace(id="s1", title="T", authors=["A"], year=2020, doi=None)
        work = extract_cited_work(cast("Source", src))
        assert work.doi is None
        assert work.arxiv_id is None
