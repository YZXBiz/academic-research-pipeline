"""Models + reducer for the deterministic citation-existence gate (spec port #182)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, computed_field


if TYPE_CHECKING:
    from collections.abc import Mapping


__all__ = [
    "CitationExistenceReport",
    "CitationVerification",
    "CitedWork",
    "LookupVerified",
    "QueryForm",
    "ResolverOutcome",
    "ResolverStatus",
    "classify_lookup",
]


class ResolverStatus(StrEnum):
    """Per-resolver lookup outcome."""

    MATCHED = "matched"
    UNMATCHED = "unmatched"
    UNREACHABLE = "unreachable"
    SKIPPED = "skipped"


class QueryForm(StrEnum):
    """How a resolver was keyed (id = DOI/arXiv/ISBN, title = fallback search)."""

    ID = "id"
    TITLE = "title"


class LookupVerified(StrEnum):
    """Existence verdict for a citation."""

    TRUE = "true"
    FALSE = "false"
    UNRESOLVABLE = "unresolvable"
    CONFLICT = "conflict"
    ID_MISMATCH = "id_mismatch"


class CitedWork(BaseModel):
    """Falsifiable input fields for one cited work."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    isbn: str | None = None


class ResolverOutcome(BaseModel):
    """One resolver's verdict on one citation."""

    model_config = ConfigDict(frozen=True)

    status: ResolverStatus
    queried_by: QueryForm | None = None
    matched_doi: str | None = None
    matched_year: int | None = None
    response_summary: str | None = None


class CitationVerification(BaseModel):
    """Existence verdict for one cited Source (source_id == Source.id == [@sNNN])."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    resolver_outcomes: dict[str, ResolverOutcome] = Field(default_factory=dict)
    lookup_verified: LookupVerified
    retracted: bool = False
    published_year: int | None = None
    verification_timestamp: datetime


class CitationExistenceReport(BaseModel):
    """Aggregate of per-citation verdicts; policy-agnostic (the node applies advisory/strict)."""

    model_config = ConfigDict(frozen=True)

    verifications: list[CitationVerification] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def by_status(self) -> dict[LookupVerified, int]:
        """Verdict counts, every key present."""
        counts: dict[LookupVerified, int] = dict.fromkeys(LookupVerified, 0)
        for v in self.verifications:
            counts[v.lookup_verified] += 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def false_rows(self) -> list[CitationVerification]:
        """Provably-bogus citations."""
        return [v for v in self.verifications if v.lookup_verified is LookupVerified.FALSE]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def retracted_rows(self) -> list[CitationVerification]:
        """Retracted-but-existing citations."""
        return [v for v in self.verifications if v.retracted]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocking_rows(self) -> list[CitationVerification]:
        """Rows a strict gate blocks (false or retracted, deduped by source_id)."""
        seen: set[str] = set()
        out: list[CitationVerification] = []
        for v in (*self.false_rows, *self.retracted_rows):
            if v.source_id not in seen:
                seen.add(v.source_id)
                out.append(v)
        return out

    @computed_field  # type: ignore[prop-decorator]
    @property
    def advisory_summary(self) -> str:
        """One-line coverage summary."""
        c = self.by_status
        return (
            f"{c[LookupVerified.TRUE]} verified, {c[LookupVerified.FALSE]} false, "
            f"{c[LookupVerified.ID_MISMATCH]} id-mismatch, {c[LookupVerified.CONFLICT]} conflict, "
            f"{c[LookupVerified.UNRESOLVABLE]} unresolvable; {len(self.retracted_rows)} retracted"
        )


def _norm_id(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def classify_lookup(
    outcomes: Mapping[str, ResolverOutcome],
    *,
    cited_doi: str | None = None,
) -> LookupVerified:
    """Reduce resolver outcomes to a verdict: id_mismatch, conflict, true, false, unresolvable."""
    values = list(outcomes.values())
    matched = [o for o in values if o.status is ResolverStatus.MATCHED]
    id_unmatched = [
        o for o in values if o.status is ResolverStatus.UNMATCHED and o.queried_by is QueryForm.ID
    ]

    if id_unmatched and cited_doi is not None:
        title_match_diff_id = [
            o
            for o in matched
            if o.queried_by is QueryForm.TITLE
            and o.matched_doi is not None
            and _norm_id(o.matched_doi) != _norm_id(cited_doi)
        ]
        if title_match_diff_id:
            return LookupVerified.ID_MISMATCH

    if matched:
        matched_years = {o.matched_year for o in matched if o.matched_year is not None}
        if len(matched_years) >= 2:
            return LookupVerified.CONFLICT
        return LookupVerified.TRUE

    if id_unmatched:
        return LookupVerified.FALSE

    return LookupVerified.UNRESOLVABLE
