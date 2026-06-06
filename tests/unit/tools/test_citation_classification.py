"""Unit tests for the citation-existence classification reducer (port-plan §2.1).

Pure logic over ResolverOutcome[]; no network. Pins the `lookup_verified`
contract including the two mutation traps and the 051/052 coverage-gap symmetry
pair (the load-bearing case: a fabricated title-only cite and a real-but-unindexed
cite are indistinguishable to the reducer, so neither may be classified `false`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from academic_pipeline.models.citation_verification import (
    CitationVerification,
    LookupVerified,
    QueryForm,
    ResolverOutcome,
    ResolverStatus,
    classify_lookup,
)


M, U, UR, SK = (
    ResolverStatus.MATCHED,
    ResolverStatus.UNMATCHED,
    ResolverStatus.UNREACHABLE,
    ResolverStatus.SKIPPED,
)
ID, TITLE = QueryForm.ID, QueryForm.TITLE


def _o(
    status: ResolverStatus,
    queried_by: QueryForm | None = None,
    matched_doi: str | None = None,
    matched_year: int | None = None,
) -> ResolverOutcome:
    return ResolverOutcome(
        status=status,
        queried_by=queried_by,
        matched_doi=matched_doi,
        matched_year=matched_year,
    )


class TestClassifyLookup:
    def test_true_when_any_matched(self) -> None:
        out = {"crossref": _o(M, ID, matched_doi="10.1/x", matched_year=2020), "s2": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi="10.1/x") is LookupVerified.TRUE

    def test_true_for_no_doi_paper_matched_by_title(self) -> None:
        out = {"s2": _o(M, TITLE, matched_doi=None, matched_year=2018), "crossref": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi=None) is LookupVerified.TRUE

    def test_false_on_id_keyed_unmatched_no_match(self) -> None:
        out = {"crossref": _o(U, ID), "s2": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi="10.1/bogus") is LookupVerified.FALSE

    def test_false_is_anti_fabrication_biased(self) -> None:
        out = {"crossref": _o(U, ID), "arxiv": _o(U, ID), "datacite": _o(U, ID), "s2": _o(UR)}
        assert classify_lookup(out, cited_doi="10.1/bogus") is LookupVerified.FALSE

    def test_unresolvable_on_title_only_unmatched(self) -> None:
        out = {"crossref": _o(U, TITLE), "s2": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi=None) is LookupVerified.UNRESOLVABLE

    def test_unresolvable_when_all_unreachable(self) -> None:
        out = {"crossref": _o(UR), "s2": _o(UR)}
        assert classify_lookup(out, cited_doi="10.1/x") is LookupVerified.UNRESOLVABLE

    def test_unresolvable_when_all_skipped_manual_entry(self) -> None:
        out = {"crossref": _o(SK), "arxiv": _o(SK)}
        assert classify_lookup(out, cited_doi=None) is LookupVerified.UNRESOLVABLE

    def test_id_mismatch_is_a_typo_of_a_real_paper_not_fabrication(self) -> None:
        out = {"crossref": _o(U, ID), "s2": _o(M, TITLE, matched_doi="10.1/real", matched_year=2019)}
        assert classify_lookup(out, cited_doi="10.1/typo") is LookupVerified.ID_MISMATCH

    def test_conflict_on_year_disagreement_between_matched_resolvers(self) -> None:
        out = {
            "crossref": _o(M, ID, matched_doi="10.1/x", matched_year=2019),
            "openalex": _o(M, ID, matched_doi="10.1/x", matched_year=2021),
        }
        assert classify_lookup(out, cited_doi="10.1/x") is LookupVerified.CONFLICT

    def test_051_fabricated_title_only_is_unresolvable(self) -> None:
        out = {"crossref": _o(U, TITLE), "openalex": _o(U, TITLE), "s2": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi=None) is LookupVerified.UNRESOLVABLE

    def test_052_valid_unindexed_is_unresolvable(self) -> None:
        out = {"crossref": _o(U, TITLE), "openalex": _o(U, TITLE), "s2": _o(U, TITLE)}
        assert classify_lookup(out, cited_doi=None) is LookupVerified.UNRESOLVABLE

    def test_empty_outcomes_is_unresolvable(self) -> None:
        assert classify_lookup({}, cited_doi=None) is LookupVerified.UNRESOLVABLE


class TestCitationVerificationModel:
    def test_is_frozen(self) -> None:
        cv = CitationVerification(
            source_id="s001",
            lookup_verified=LookupVerified.TRUE,
            verification_timestamp=datetime(2026, 6, 5, tzinfo=UTC),
        )
        with pytest.raises(Exception):  # noqa: B017
            cv.source_id = "s002"  # type: ignore[misc]

    def test_retracted_is_independent_of_classification(self) -> None:
        cv = CitationVerification(
            source_id="s001",
            lookup_verified=LookupVerified.TRUE,
            retracted=True,
            verification_timestamp=datetime(2026, 6, 5, tzinfo=UTC),
        )
        assert cv.retracted is True
        assert cv.lookup_verified is LookupVerified.TRUE
