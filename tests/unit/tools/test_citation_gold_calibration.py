"""Gold-set calibration gate for classify_lookup (spec §8).

Seed set covering every verdict class. Expand with recorded real-API resolver
outcomes; the threshold gate below is the CI done-criterion for the reducer.
"""

from __future__ import annotations

from academic_pipeline.models.citation_verification import (
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
    return ResolverOutcome(status=status, queried_by=queried_by, matched_doi=matched_doi, matched_year=matched_year)


_GOLD: list[tuple[dict[str, ResolverOutcome], str | None, LookupVerified]] = [
    ({"crossref": _o(M, ID, "10.1/a", 2017)}, "10.1/a", LookupVerified.TRUE),
    ({"s2": _o(M, TITLE, None, 2018)}, None, LookupVerified.TRUE),
    ({"crossref": _o(M, ID, "10.1/b", 2019), "openalex": _o(M, ID, "10.1/b", 2019)}, "10.1/b", LookupVerified.TRUE),
    ({"crossref": _o(U, ID)}, "10.1/bogus", LookupVerified.FALSE),
    ({"arxiv": _o(U, ID)}, None, LookupVerified.FALSE),
    ({"crossref": _o(U, ID), "arxiv": _o(U, ID), "datacite": _o(U, ID), "s2": _o(UR)}, "10.1/x", LookupVerified.FALSE),
    ({"crossref": _o(U, TITLE), "s2": _o(U, TITLE)}, None, LookupVerified.UNRESOLVABLE),
    ({"crossref": _o(U, TITLE), "openalex": _o(U, TITLE)}, None, LookupVerified.UNRESOLVABLE),
    ({"crossref": _o(UR), "s2": _o(UR)}, "10.1/x", LookupVerified.UNRESOLVABLE),
    ({"crossref": _o(SK), "arxiv": _o(SK)}, None, LookupVerified.UNRESOLVABLE),
    ({"crossref": _o(U, ID), "s2": _o(M, TITLE, "10.1/real", 2019)}, "10.1/typo", LookupVerified.ID_MISMATCH),
    ({"crossref": _o(M, ID, "10.1/c", 2019), "openalex": _o(M, ID, "10.1/c", 2021)}, "10.1/c", LookupVerified.CONFLICT),
]


def _score() -> tuple[float, dict[LookupVerified, float]]:
    correct = sum(1 for outcomes, doi, expected in _GOLD if classify_lookup(outcomes, cited_doi=doi) is expected)
    per_class: dict[LookupVerified, float] = {}
    for cls in LookupVerified:
        cases = [(o, d, e) for o, d, e in _GOLD if e is cls]
        if cases:
            hits = sum(1 for o, d, e in cases if classify_lookup(o, cited_doi=d) is e)
            per_class[cls] = hits / len(cases)
    return correct / len(_GOLD), per_class


def test_gold_set_meets_thresholds() -> None:
    aggregate, per_class = _score()
    assert aggregate >= 0.90
    for cls in (LookupVerified.TRUE, LookupVerified.FALSE, LookupVerified.UNRESOLVABLE):
        assert per_class[cls] >= 0.85


def test_gold_set_covers_every_verdict() -> None:
    covered = {expected for _, _, expected in _GOLD}
    assert covered == set(LookupVerified)
