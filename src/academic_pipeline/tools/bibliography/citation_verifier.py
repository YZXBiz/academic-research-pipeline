"""Citation-existence orchestrator: metadata-match veto + resolver triangulation."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from academic_pipeline.models.citation_verification import (
    CitationExistenceReport,
    CitationVerification,
    CitedWork,
    LookupVerified,
    ResolverOutcome,
    ResolverStatus,
    classify_lookup,
)
from academic_pipeline.tools.bibliography.semantic_scholar import _title_similarity


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from academic_pipeline.models.shared import Source
    from academic_pipeline.tools.bibliography.verification_cache import VerificationCache

    Resolver = Callable[[CitedWork], Awaitable[ResolverOutcome]]
    RetractionCheck = Callable[[str], Awaitable[bool]]


logger = logging.getLogger(__name__)

DEFAULT_TAU = 0.85
DEFAULT_YEAR_TOL = 1
DEFAULT_MARGIN = 0.05
GLOBAL_CONCURRENCY = 8

_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)


class Candidate(BaseModel):
    """A resolver-returned record to metadata-match against the cited work."""

    model_config = ConfigDict(frozen=True)

    identifier: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None


class MatchResult(BaseModel):
    """Metadata-match result."""

    model_config = ConfigDict(frozen=True)

    matched: bool
    matched_id: str | None = None
    matched_year: int | None = None


def extract_cited_work(source: Source) -> CitedWork:
    """Build a CitedWork from a Source (arXiv ID derived from an arXiv DOI)."""
    arxiv_id: str | None = None
    if source.doi:
        m = _ARXIV_DOI_RE.match(source.doi.strip())
        if m:
            arxiv_id = m.group(1)
    return CitedWork(
        source_id=source.id,
        title=source.title,
        authors=list(source.authors),
        year=source.year,
        doi=source.doi,
        arxiv_id=arxiv_id,
    )


def _surnames(authors: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for a in authors:
        token = a.strip().rstrip(".,").split()
        if token:
            out.add(token[-1].strip(",.").lower())
    return out


def _author_overlap(cited: Sequence[str], candidate: Sequence[str]) -> bool:
    cited_s = _surnames(cited)
    candidate_s = _surnames(candidate)
    if not cited_s or not candidate_s:
        return True
    return bool(cited_s & candidate_s)


def metadata_match(
    work: CitedWork,
    candidates: Sequence[Candidate],
    *,
    tau: float = DEFAULT_TAU,
    year_tol: int = DEFAULT_YEAR_TOL,
    margin: float = DEFAULT_MARGIN,
) -> MatchResult:
    """Match a cited work against candidates with a title+author+year+margin veto."""
    if not candidates:
        return MatchResult(matched=False)

    scored = sorted(
        ((_title_similarity(work.title, c.title), c) for c in candidates),
        key=lambda t: t[0],
        reverse=True,
    )
    best_sim, best = scored[0]
    second_sim = scored[1][0] if len(scored) > 1 else 0.0

    if best_sim < tau:
        return MatchResult(matched=False)
    if not _author_overlap(work.authors, best.authors):
        return MatchResult(matched=False)
    if work.year is not None and best.year is not None and abs(work.year - best.year) > year_tol:
        return MatchResult(matched=False)
    if len(scored) > 1 and (best_sim - second_sim) < margin:
        return MatchResult(matched=False)

    return MatchResult(matched=True, matched_id=best.identifier, matched_year=best.year)


async def verify_citation(
    work: CitedWork,
    *,
    resolvers: Mapping[str, Resolver],
    retraction_check: RetractionCheck | None = None,
    now: datetime | None = None,
) -> CitationVerification:
    """Run all resolvers for one work, classify, attach retraction + year."""
    names = list(resolvers)
    raw = await asyncio.gather(
        *(resolvers[name](work) for name in names),
        return_exceptions=True,
    )

    outcomes: dict[str, ResolverOutcome] = {}
    for name, result in zip(names, raw, strict=True):
        if isinstance(result, ResolverOutcome):
            outcomes[name] = result
        else:
            logger.warning("resolver %s raised for %s: %r", name, work.source_id, result)
            outcomes[name] = ResolverOutcome(status=ResolverStatus.UNREACHABLE)

    lookup = classify_lookup(outcomes, cited_doi=work.doi)

    retracted = False
    if work.doi and retraction_check is not None and lookup in (LookupVerified.TRUE, LookupVerified.CONFLICT):
        try:
            retracted = bool(await retraction_check(work.doi))
        except Exception as exc:
            logger.warning("retraction_check raised for %s: %r", work.doi, exc)

    published_year = next((o.matched_year for o in outcomes.values() if o.matched_year is not None), None)

    return CitationVerification(
        source_id=work.source_id,
        resolver_outcomes=outcomes,
        lookup_verified=lookup,
        retracted=retracted,
        published_year=published_year,
        verification_timestamp=now or datetime.now(UTC),
    )


async def verify_corpus(
    works: Sequence[CitedWork],
    *,
    resolvers: Mapping[str, Resolver],
    retraction_check: RetractionCheck | None = None,
    concurrency: int = GLOBAL_CONCURRENCY,
    now: datetime | None = None,
) -> list[CitationVerification]:
    """Verify every work bounded by a global concurrency cap; order preserved."""
    sem = asyncio.Semaphore(concurrency)

    async def _one(work: CitedWork) -> CitationVerification:
        async with sem:
            return await verify_citation(
                work, resolvers=resolvers, retraction_check=retraction_check, now=now
            )

    return list(await asyncio.gather(*(_one(w) for w in works)))


async def run_citation_gate(
    sources: Sequence[Source],
    *,
    mailto: str,
    resolvers: Mapping[str, Resolver] | None = None,
    retraction_check: RetractionCheck | None = None,
    cache: VerificationCache | None = None,
    now: datetime | None = None,
) -> CitationExistenceReport:
    """Verify a bibliography's sources and aggregate them into a report."""
    from academic_pipeline.tools.bibliography.resolvers import default_resolvers

    works = [extract_cited_work(s) for s in sources]
    res = resolvers if resolvers is not None else default_resolvers(mailto=mailto)
    if cache is not None:
        from academic_pipeline.tools.bibliography.verification_cache import cached_resolvers

        res = cached_resolvers(res, cache)
    verifications = await verify_corpus(works, resolvers=res, retraction_check=retraction_check, now=now)
    return CitationExistenceReport(verifications=verifications)


def _cli() -> None:
    import argparse
    import json
    import sys

    from academic_pipeline.config import DEFAULT_CONFIG
    from academic_pipeline.tools.bibliography.resolvers import default_resolvers

    parser = argparse.ArgumentParser(description="Verify one citation's existence.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--doi")
    parser.add_argument("--arxiv")
    parser.add_argument("--year", type=int)
    parser.add_argument("--author", action="append", default=[])
    args = parser.parse_args()

    work = CitedWork(
        source_id="cli",
        title=args.title,
        authors=args.author,
        year=args.year,
        doi=args.doi,
        arxiv_id=args.arxiv,
    )
    cv = asyncio.run(
        verify_citation(work, resolvers=default_resolvers(mailto=DEFAULT_CONFIG.crossref_mailto))
    )
    sys.stdout.write(json.dumps(cv.model_dump(mode="json"), indent=2, default=str) + "\n")


if __name__ == "__main__":
    _cli()
