"""Tests for SourceVerificationNode verification override."""
from __future__ import annotations

from academic_pipeline.models.shared import Source
from academic_pipeline.models.research import (
    Bibliography,
    PRISMACounts,
    SearchStrategy,
)


def _make_source(sid: str, verified: bool | None = True) -> Source:
    return Source(
        id=sid, title=f"Test Paper {sid}", authors=["Author A"], year=2024,
        doi=f"10.1234/{sid}", citation=f"Author A. (2024). Test Paper {sid}. Journal, 1(1), 1-10.",
        type="journal_article", evidence_tier=2, quality_tier="tier_1",
        relevance="core", relevance_score=8, annotation="Test annotation.",
        verified=verified, retraction_check=verified,
    )


def _make_bibliography(sources: list[Source]) -> Bibliography:
    return Bibliography(
        sources=sources,
        search_strategy=SearchStrategy(
            databases=["Exa"], keywords=["test"],
            inclusion_criteria=["relevant"], exclusion_criteria=["irrelevant"],
            date_range="2020-2025",
        ),
        coverage_assessment="Good coverage.", minimum_sources=1,
        prisma_counts=PRISMACounts(identified=10, screened=8, eligible=5, included=3),
    )


def test_rebuild_bibliography_with_verification():
    from academic_pipeline.research.graph import rebuild_bibliography_with_verification
    sources = [_make_source("S1", True), _make_source("S2", True), _make_source("S3", True)]
    bib = _make_bibliography(sources)
    verification_results = {"S1": True, "S2": False}
    new_bib = rebuild_bibliography_with_verification(bib, verification_results)
    assert new_bib.sources[0].verified is True
    assert new_bib.sources[1].verified is False
    assert new_bib.sources[2].verified is None


def test_rebuild_preserves_other_fields():
    from academic_pipeline.research.graph import rebuild_bibliography_with_verification
    sources = [_make_source("S1", True)]
    bib = _make_bibliography(sources)
    new_bib = rebuild_bibliography_with_verification(bib, {"S1": True})
    assert new_bib.sources[0].title == "Test Paper S1"
    assert new_bib.coverage_assessment == "Good coverage."
