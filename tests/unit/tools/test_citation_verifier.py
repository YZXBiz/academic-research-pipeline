"""Unit tests for the citation-existence orchestrator + metadata-match veto.

`metadata_match` is pure; `verify_citation`/`verify_corpus` use injected fake
resolvers, so nothing here hits the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from academic_pipeline.models.citation_verification import (
    CitedWork,
    LookupVerified,
    QueryForm,
    ResolverOutcome,
    ResolverStatus,
)
from academic_pipeline.tools.bibliography.citation_verifier import (
    Candidate,
    metadata_match,
    run_citation_gate,
    verify_citation,
    verify_corpus,
)


if TYPE_CHECKING:
    from academic_pipeline.models.shared import Source


M, U = ResolverStatus.MATCHED, ResolverStatus.UNMATCHED
ID, TITLE = QueryForm.ID, QueryForm.TITLE
_NOW = datetime(2026, 6, 5, tzinfo=UTC)


def _work(**kw: object) -> CitedWork:
    base: dict[str, object] = {
        "source_id": "s001",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani"],
        "year": 2017,
        "doi": "10.1/attn",
    }
    base.update(kw)
    return CitedWork(**base)  # type: ignore[arg-type]


def _resolver(outcome: ResolverOutcome):
    async def _r(_w: CitedWork) -> ResolverOutcome:
        return outcome

    return _r


def _raising():
    async def _r(_w: CitedWork) -> ResolverOutcome:
        raise RuntimeError("boom")

    return _r


class TestMetadataMatch:
    def test_exact_single_candidate_matches(self) -> None:
        work = _work()
        cands = [Candidate(identifier="10.1/attn", title="Attention Is All You Need", authors=["Vaswani"], year=2017)]
        r = metadata_match(work, cands)
        assert r.matched is True
        assert r.matched_id == "10.1/attn"
        assert r.matched_year == 2017

    def test_low_title_similarity_is_unmatched(self) -> None:
        work = _work()
        cands = [Candidate(title="Lattice Gauge Theory of Quark Confinement", authors=["Vaswani"], year=2017)]
        assert metadata_match(work, cands).matched is False

    def test_author_veto_blocks_title_collision_false_pass(self) -> None:
        work = _work(authors=["Faker"])
        cands = [Candidate(identifier="10.1/real", title="Attention Is All You Need", authors=["Vaswani"], year=2017)]
        assert metadata_match(work, cands).matched is False

    def test_year_veto(self) -> None:
        work = _work(year=2010)
        cands = [Candidate(title="Attention Is All You Need", authors=["Vaswani"], year=2017)]
        assert metadata_match(work, cands).matched is False

    def test_runner_up_margin_rejects_ambiguous_collision(self) -> None:
        work = _work()
        cands = [
            Candidate(identifier="10.1/a", title="Attention Is All You Need", authors=["Vaswani"], year=2017),
            Candidate(identifier="10.1/b", title="Attention Is All You Need.", authors=["Vaswani"], year=2017),
        ]
        assert metadata_match(work, cands).matched is False

    def test_empty_candidates_is_unmatched(self) -> None:
        assert metadata_match(_work(), []).matched is False

    def test_missing_cited_authors_skips_author_veto(self) -> None:
        work = _work(authors=[])
        cands = [Candidate(identifier="10.1/attn", title="Attention Is All You Need", authors=["Vaswani"], year=2017)]
        assert metadata_match(work, cands).matched is True


pytestmark = pytest.mark.anyio


class TestVerifyCitation:
    async def test_all_matched_is_true_with_year_and_injected_timestamp(self) -> None:
        resolvers = {
            "crossref": _resolver(ResolverOutcome(status=M, queried_by=ID, matched_doi="10.1/attn", matched_year=2017)),
            "s2": _resolver(ResolverOutcome(status=M, queried_by=TITLE, matched_year=2017)),
        }
        cv = await verify_citation(_work(), resolvers=resolvers, now=_NOW)
        assert cv.lookup_verified is LookupVerified.TRUE
        assert cv.published_year == 2017
        assert cv.verification_timestamp == _NOW
        assert cv.source_id == "s001"

    async def test_id_keyed_unmatched_is_false(self) -> None:
        resolvers = {"crossref": _resolver(ResolverOutcome(status=U, queried_by=ID))}
        cv = await verify_citation(_work(doi="10.1/bogus"), resolvers=resolvers, now=_NOW)
        assert cv.lookup_verified is LookupVerified.FALSE

    async def test_resolver_exception_becomes_unreachable_not_unmatched(self) -> None:
        resolvers = {
            "crossref": _raising(),
            "s2": _resolver(ResolverOutcome(status=M, queried_by=TITLE, matched_year=2017)),
        }
        cv = await verify_citation(_work(), resolvers=resolvers, now=_NOW)
        assert cv.resolver_outcomes["crossref"].status is ResolverStatus.UNREACHABLE
        assert cv.lookup_verified is LookupVerified.TRUE

    async def test_retraction_checked_only_on_existing_paper(self) -> None:
        calls: list[str] = []

        async def _retraction(doi: str) -> bool:
            calls.append(doi)
            return True

        cv = await verify_citation(
            _work(),
            resolvers={"crossref": _resolver(ResolverOutcome(status=M, queried_by=ID, matched_year=2017))},
            retraction_check=_retraction,
            now=_NOW,
        )
        assert cv.retracted is True
        assert calls == ["10.1/attn"]

        calls.clear()
        cv2 = await verify_citation(
            _work(doi="10.1/bogus"),
            resolvers={"crossref": _resolver(ResolverOutcome(status=U, queried_by=ID))},
            retraction_check=_retraction,
            now=_NOW,
        )
        assert cv2.retracted is False
        assert calls == []


class TestVerifyCorpus:
    async def test_maps_over_sources_preserving_order(self) -> None:
        works = [_work(source_id="s001"), _work(source_id="s002", doi="10.1/bogus")]
        resolvers = {
            "crossref": _resolver(ResolverOutcome(status=M, queried_by=ID, matched_year=2017)),
        }
        out = await verify_corpus(works, resolvers=resolvers, now=_NOW)
        assert [c.source_id for c in out] == ["s001", "s002"]
        assert all(c.lookup_verified is LookupVerified.TRUE for c in out)


class TestRunCitationGate:
    async def test_aggregates_sources_into_report(self) -> None:
        def _doi_resolver(good: str):
            async def _r(work: CitedWork) -> ResolverOutcome:
                if work.doi == good:
                    return ResolverOutcome(status=M, queried_by=ID, matched_doi=work.doi, matched_year=2017)
                return ResolverOutcome(status=U, queried_by=ID)

            return _r

        sources = [
            SimpleNamespace(id="s1", title="Real", authors=["A"], year=2017, doi="10.1/real"),
            SimpleNamespace(id="s2", title="Fake", authors=["B"], year=2020, doi="10.1/bogus"),
        ]
        report = await run_citation_gate(
            cast("list[Source]", sources),
            mailto="x",
            resolvers={"crossref": _doi_resolver("10.1/real")},
            now=_NOW,
        )
        assert report.by_status[LookupVerified.TRUE] == 1
        assert report.by_status[LookupVerified.FALSE] == 1
        assert [v.source_id for v in report.blocking_rows] == ["s2"]
