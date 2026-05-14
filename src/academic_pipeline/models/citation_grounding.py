"""Domain models for the citation-grounding audit.

Built from the close-read of run-0511-2107_6271 (see
docs/architecture/hardening-targets-run-0511-2107.md). The dominant defect
class was section writers attaching citations to claims the cited source does
not actually support — e.g. TAM cited to s001 (Sculley's ML technical-debt
paper) instead of s007 (Davis 1989). The pipeline already has the ground
truth in each bibliography source's `annotation`; the citation_grounding
agent pairs every in-text `[@sNNN]` use with its source annotation and
classifies the match.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


__all__ = [
    "CitationGroundingReport",
    "CitationUsage",
    "CitationVerdict",
]


class CitationVerdict(StrEnum):
    """The grounding verdict for one citation usage.

    SUPPORTS / TANGENTIAL pass; CONTRADICTS / UNSUPPORTED are 'critical
    mismatches' and route to the integrity-fix loop.
    """

    SUPPORTS = "supports"
    """Cited source's annotation directly substantiates the surrounding claim."""

    TANGENTIAL = "tangential"
    """Source is related to the topic but doesn't specifically substantiate the claim."""

    CONTRADICTS = "contradicts"
    """Source's actual finding contradicts how it's being used in the prose."""

    UNSUPPORTED = "unsupported"
    """Source is irrelevant to the claim (wrong-source citation)."""


class CitationUsage(BaseModel):
    """One `[@sNNN]` citation as it appears in the paper draft."""

    model_config = ConfigDict(frozen=True)

    citation_id: str = Field(description="Source key as used in pandoc, e.g. 's007'.")
    claim_text: str = Field(
        description="The sentence (or clause) in the paper that the citation supports.",
    )
    section: str = Field(
        description="The paper section heading the citation appears under, e.g. 'Introduction'.",
    )
    verdict: CitationVerdict
    reasoning: str = Field(
        description="1-2 sentence explanation of why this verdict was reached.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Auditor's confidence in the verdict, in [0, 1].",
    )


class CitationGroundingReport(BaseModel):
    """Result of running citation-grounding over the full paper draft."""

    model_config = ConfigDict(frozen=True)

    usages: list[CitationUsage] = Field(
        default_factory=list,
        description="One entry per in-text citation occurrence.",
    )
    summary: str = Field(
        description="Brief assessment of citation grounding across the paper.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_citations(self) -> int:
        """Total number of citation occurrences audited."""
        return len(self.usages)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def by_verdict(self) -> dict[CitationVerdict, int]:
        """Count of usages bucketed by verdict; every verdict key is present."""
        counts: dict[CitationVerdict, int] = dict.fromkeys(CitationVerdict, 0)
        for usage in self.usages:
            counts[usage.verdict] += 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def critical_mismatches(self) -> list[CitationUsage]:
        """Usages with a CONTRADICTS or UNSUPPORTED verdict — the blocking class."""
        return [
            u
            for u in self.usages
            if u.verdict in (CitationVerdict.CONTRADICTS, CitationVerdict.UNSUPPORTED)
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_pass(self) -> bool:
        """True when no citation usage is a critical mismatch."""
        return not self.critical_mismatches
