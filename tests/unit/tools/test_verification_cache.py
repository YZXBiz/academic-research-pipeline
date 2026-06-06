"""Tests for the SQLite verification cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from academic_pipeline.models.citation_verification import CitedWork, QueryForm, ResolverOutcome, ResolverStatus
from academic_pipeline.tools.bibliography.verification_cache import VerificationCache, cached_resolver


if TYPE_CHECKING:
    from pathlib import Path


M, U, UR = ResolverStatus.MATCHED, ResolverStatus.UNMATCHED, ResolverStatus.UNREACHABLE
ID = QueryForm.ID


def _work() -> CitedWork:
    return CitedWork(source_id="s1", title="T", doi="10.1/x")


class TestCacheStore:
    def test_round_trip(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "v.db")
        cache.put("k", ResolverOutcome(status=M, queried_by=ID, matched_doi="10.1/x", matched_year=2020), now=100.0)
        got = cache.get("k", now=101.0)
        assert got is not None
        assert got.status is M
        assert got.matched_doi == "10.1/x"
        cache.close()

    def test_miss(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "v.db")
        assert cache.get("nope") is None
        cache.close()

    def test_ttl_expiry(self, tmp_path: Path) -> None:
        cache = VerificationCache(tmp_path / "v.db")
        cache.put("k", ResolverOutcome(status=U, queried_by=ID), now=0.0)
        assert cache.get("k", ttl=10, now=5.0) is not None
        assert cache.get("k", ttl=10, now=20.0) is None
        cache.close()


pytestmark = pytest.mark.anyio


class TestCachedResolver:
    async def test_hit_avoids_second_call(self, tmp_path: Path) -> None:
        calls: list[int] = []

        async def _r(_w: CitedWork) -> ResolverOutcome:
            calls.append(1)
            return ResolverOutcome(status=M, queried_by=ID, matched_doi="10.1/x", matched_year=2020)

        cache = VerificationCache(tmp_path / "v.db")
        wrapped = cached_resolver("crossref", _r, cache)
        await wrapped(_work())
        await wrapped(_work())
        assert len(calls) == 1
        cache.close()

    async def test_unreachable_not_cached(self, tmp_path: Path) -> None:
        calls: list[int] = []

        async def _r(_w: CitedWork) -> ResolverOutcome:
            calls.append(1)
            return ResolverOutcome(status=UR)

        cache = VerificationCache(tmp_path / "v.db")
        wrapped = cached_resolver("crossref", _r, cache)
        await wrapped(_work())
        await wrapped(_work())
        assert len(calls) == 2
        cache.close()
