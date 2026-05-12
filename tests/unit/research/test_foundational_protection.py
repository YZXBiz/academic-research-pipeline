"""Tests for foundational source protection during bibliography revision."""
from __future__ import annotations

from academic_pipeline.models.shared import Source
from academic_pipeline.research.graph import check_foundational_sources_retained


def _make_source(sid: str, evidence_tier: int = 3) -> Source:
    return Source(
        id=sid,
        title=f"Paper {sid}",
        authors=["Author"],
        year=2024,
        citation=f"Citation {sid}",
        type="journal_article",
        evidence_tier=evidence_tier,
        quality_tier="tier_1",
        relevance="core",
        relevance_score=8,
        annotation="Test.",
    )


def test_no_dropped_foundational_returns_empty():
    original = [_make_source("S1", 1), _make_source("S2", 3)]
    revised = [_make_source("S1", 1), _make_source("S2", 3)]
    dropped = check_foundational_sources_retained(original, revised)
    assert dropped == []


def test_dropped_meta_analysis_detected():
    original = [_make_source("S1", 1), _make_source("S2", 3)]
    revised = [_make_source("S2", 3)]
    dropped = check_foundational_sources_retained(original, revised)
    assert len(dropped) == 1
    assert dropped[0].id == "S1"


def test_dropped_systematic_review_detected():
    original = [_make_source("S1", 2), _make_source("S2", 4)]
    revised = [_make_source("S2", 4)]
    dropped = check_foundational_sources_retained(original, revised)
    assert len(dropped) == 1
    assert dropped[0].id == "S1"


def test_dropped_tier3_not_flagged():
    original = [_make_source("S1", 3), _make_source("S2", 4)]
    revised = [_make_source("S2", 4)]
    dropped = check_foundational_sources_retained(original, revised)
    assert dropped == []
