"""Tests for the helper that joins parsed citations with bibliography annotations.

This is the bridge between the citation parser (which knows only the paper)
and the citation_grounding agent (which needs the cited source's annotation
to do the semantic-match check).
"""

from __future__ import annotations

import dataclasses

import pytest

from academic_pipeline.models.research import (
    Bibliography,
    SearchStrategy,
)
from academic_pipeline.models.shared import Source
from academic_pipeline.writing.citation_grounding import (
    GroundingPair,
    ParsedCitation,
    build_grounding_pairs,
)


def _source(id_: str, *, annotation: str = "Generic annotation.") -> Source:
    return Source(
        id=id_,
        title=f"Title for {id_}",
        authors=[f"Author{id_}"],
        year=2024,
        doi=None,
        citation=f"Author{id_} (2024). Title for {id_}.",
        type="journal_article",
        evidence_tier=5,
        quality_tier="tier_2",
        relevance="core",
        relevance_score=8,
        annotation=annotation,
    )


def _bibliography(sources: list[Source]) -> Bibliography:
    return Bibliography(
        sources=sources,
        search_strategy=SearchStrategy(
            databases=["arxiv"],
            keywords=["test"],
            inclusion_criteria=["a"],
            exclusion_criteria=["b"],
            date_range="2020-2024",
        ),
        coverage_assessment="ok",
        minimum_sources=1,
    )


def test_pair_includes_citation_context_and_source_annotation() -> None:
    bib = _bibliography(
        [
            _source(
                "s007",
                annotation="Davis 1989 foundational TAM paper with PU and PEOU scales.",
            ),
        ]
    )
    citations = [
        ParsedCitation(
            citation_id="s007",
            claim_text="TAM posits two adoption drivers [@s007].",
            section="Introduction",
        ),
    ]
    pairs = build_grounding_pairs(bib, citations)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.citation_id == "s007"
    assert pair.claim_text == "TAM posits two adoption drivers [@s007]."
    assert pair.section == "Introduction"
    assert pair.source_title == "Title for s007"
    assert pair.source_year == 2024
    assert "TAM" in pair.source_annotation


def test_orphan_citation_is_omitted() -> None:
    """If the cited id isn't in the bibliography, skip — citation_compliance handles orphans."""
    bib = _bibliography([_source("s001"), _source("s007")])
    citations = [
        ParsedCitation(citation_id="s001", claim_text="A [@s001].", section="Intro"),
        ParsedCitation(citation_id="s999", claim_text="B [@s999].", section="Intro"),
        ParsedCitation(citation_id="s007", claim_text="C [@s007].", section="Intro"),
    ]
    pairs = build_grounding_pairs(bib, citations)
    assert [p.citation_id for p in pairs] == ["s001", "s007"]


def test_same_id_cited_twice_yields_two_pairs() -> None:
    """A citation reused at two different claims gets verified at each usage."""
    bib = _bibliography([_source("s007", annotation="TAM")])
    citations = [
        ParsedCitation(citation_id="s007", claim_text="First use [@s007].", section="Intro"),
        ParsedCitation(citation_id="s007", claim_text="Second use [@s007].", section="Discussion"),
    ]
    pairs = build_grounding_pairs(bib, citations)
    assert len(pairs) == 2
    assert {p.section for p in pairs} == {"Intro", "Discussion"}


def test_ordering_preserved() -> None:
    bib = _bibliography([_source("s001"), _source("s002"), _source("s003")])
    citations = [
        ParsedCitation(citation_id="s003", claim_text="x", section="A"),
        ParsedCitation(citation_id="s001", claim_text="y", section="B"),
        ParsedCitation(citation_id="s002", claim_text="z", section="C"),
    ]
    pairs = build_grounding_pairs(bib, citations)
    assert [p.citation_id for p in pairs] == ["s003", "s001", "s002"]


def test_grounding_pair_is_immutable() -> None:
    """GroundingPair is a frozen dataclass — agent inputs must not be mutated."""
    pair = GroundingPair(
        citation_id="s007",
        claim_text="claim",
        section="Intro",
        source_title="title",
        source_year=2024,
        source_annotation="annotation",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.citation_id = "s001"  # type: ignore[misc]
