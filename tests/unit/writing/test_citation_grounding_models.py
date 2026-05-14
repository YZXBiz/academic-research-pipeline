"""Unit tests for citation_grounding domain models.

The citation_grounding component closes the dominant failure class observed in
run-0511-2107_6271: section writers attach citations to claims that don't match
the cited source's actual content (e.g. TAM attributed to s001=Sculley instead
of s007=Davis 1989). The report model captures verdict counts and exposes a
single `overall_pass` boolean the writing graph uses to route to integrity-fix.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_pipeline.models.citation_grounding import (
    CitationGroundingReport,
    CitationUsage,
    CitationVerdict,
)


def _usage(verdict: CitationVerdict, *, citation_id: str = "s007") -> CitationUsage:
    """Build a minimal CitationUsage with the given verdict."""
    return CitationUsage(
        citation_id=citation_id,
        claim_text="TAM posits that perceived usefulness and ease of use drive adoption.",
        section="Introduction",
        verdict=verdict,
        reasoning="Davis 1989 is the foundational TAM paper.",
        confidence=0.9,
    )


class TestCitationVerdictEnum:
    def test_has_four_distinct_verdicts(self) -> None:
        """SUPPORTS / TANGENTIAL / CONTRADICTS / UNSUPPORTED is the verdict surface."""
        assert {v.value for v in CitationVerdict} == {
            "supports",
            "tangential",
            "contradicts",
            "unsupported",
        }


class TestCitationUsage:
    def test_confidence_must_be_in_unit_interval(self) -> None:
        """Confidence outside [0, 1] is a model bug; reject at construction time."""
        with pytest.raises(ValidationError):
            CitationUsage(
                citation_id="s007",
                claim_text="claim",
                section="Introduction",
                verdict=CitationVerdict.SUPPORTS,
                reasoning="reason",
                confidence=1.5,
            )

    def test_is_frozen(self) -> None:
        """Per project convention; once an audit emits a usage, callers must not mutate it."""
        usage = _usage(CitationVerdict.SUPPORTS)
        with pytest.raises(ValidationError):
            usage.confidence = 0.1  # type: ignore[misc]


class TestCitationGroundingReport:
    def test_overall_pass_true_when_no_critical_mismatches(self) -> None:
        """SUPPORTS and TANGENTIAL alone pass; only CONTRADICTS/UNSUPPORTED block."""
        report = CitationGroundingReport(
            usages=[
                _usage(CitationVerdict.SUPPORTS),
                _usage(CitationVerdict.TANGENTIAL, citation_id="s011"),
            ],
            summary="No critical mismatches.",
        )
        assert report.overall_pass is True

    def test_overall_pass_false_when_any_contradicts(self) -> None:
        report = CitationGroundingReport(
            usages=[
                _usage(CitationVerdict.SUPPORTS),
                _usage(CitationVerdict.CONTRADICTS, citation_id="s001"),
            ],
            summary="One contradicts.",
        )
        assert report.overall_pass is False

    def test_overall_pass_false_when_any_unsupported(self) -> None:
        report = CitationGroundingReport(
            usages=[
                _usage(CitationVerdict.UNSUPPORTED, citation_id="s001"),
            ],
            summary="Source is irrelevant.",
        )
        assert report.overall_pass is False

    def test_total_citations_counts_all_usages(self) -> None:
        report = CitationGroundingReport(
            usages=[
                _usage(CitationVerdict.SUPPORTS),
                _usage(CitationVerdict.SUPPORTS, citation_id="s002"),
                _usage(CitationVerdict.CONTRADICTS, citation_id="s001"),
            ],
            summary="Three usages.",
        )
        assert report.total_citations == 3

    def test_by_verdict_buckets_each_usage_into_its_verdict(self) -> None:
        report = CitationGroundingReport(
            usages=[
                _usage(CitationVerdict.SUPPORTS),
                _usage(CitationVerdict.SUPPORTS, citation_id="s002"),
                _usage(CitationVerdict.TANGENTIAL, citation_id="s011"),
                _usage(CitationVerdict.CONTRADICTS, citation_id="s001"),
            ],
            summary="Mixed.",
        )
        assert report.by_verdict == {
            CitationVerdict.SUPPORTS: 2,
            CitationVerdict.TANGENTIAL: 1,
            CitationVerdict.CONTRADICTS: 1,
            CitationVerdict.UNSUPPORTED: 0,
        }

    def test_critical_mismatches_returns_only_contradicts_and_unsupported(self) -> None:
        """SUPPORTS and TANGENTIAL are not 'critical' — only outright wrong attributions are."""
        supports = _usage(CitationVerdict.SUPPORTS)
        tangential = _usage(CitationVerdict.TANGENTIAL, citation_id="s011")
        contradicts = _usage(CitationVerdict.CONTRADICTS, citation_id="s001")
        unsupported = _usage(CitationVerdict.UNSUPPORTED, citation_id="s003")
        report = CitationGroundingReport(
            usages=[supports, tangential, contradicts, unsupported],
            summary="Mixed.",
        )
        assert report.critical_mismatches == [contradicts, unsupported]

    def test_empty_usages_passes_with_zero_total(self) -> None:
        """A paper with zero citations is vacuously consistent (degenerate but not an error)."""
        report = CitationGroundingReport(usages=[], summary="No citations to ground.")
        assert report.total_citations == 0
        assert report.overall_pass is True
        assert report.critical_mismatches == []
