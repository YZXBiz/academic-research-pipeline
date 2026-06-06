"""Deterministic temporal verification: a citation dated after the paper is impossible."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, computed_field


if TYPE_CHECKING:
    from collections.abc import Sequence

    from academic_pipeline.models.citation_verification import CitationVerification


__all__ = [
    "TemporalFinding",
    "TemporalKind",
    "TemporalReport",
    "verify_temporal",
]


class TemporalKind(StrEnum):
    """Deterministic temporal-impossibility kind."""

    FUTURE_AS_PAST = "future_as_past"


class TemporalFinding(BaseModel):
    """One temporally-impossible citation."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    kind: TemporalKind
    cited_year: int
    reference_year: int


class TemporalReport(BaseModel):
    """Aggregate of temporal findings."""

    model_config = ConfigDict(frozen=True)

    findings: list[TemporalFinding] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocking_rows(self) -> list[TemporalFinding]:
        """Every temporal finding is an impossibility, so all block under strict."""
        return list(self.findings)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        """One-line summary."""
        return f"{len(self.findings)} temporally-impossible citation(s)"


def verify_temporal(
    verifications: Sequence[CitationVerification],
    *,
    reference_year: int,
) -> TemporalReport:
    """Flag citations whose published year is after the paper's reference year."""
    findings = [
        TemporalFinding(
            source_id=v.source_id,
            kind=TemporalKind.FUTURE_AS_PAST,
            cited_year=v.published_year,
            reference_year=reference_year,
        )
        for v in verifications
        if v.published_year is not None and v.published_year > reference_year
    ]
    return TemporalReport(findings=findings)
