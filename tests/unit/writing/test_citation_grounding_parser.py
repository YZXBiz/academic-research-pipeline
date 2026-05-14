"""Parser tests for citation-grounding.

The parser walks a paper draft Markdown and extracts every in-text citation
occurrence paired with (a) the sentence that cites it and (b) the section
heading it appears under. The grounding agent then asks an LLM to verify
each (claim, citation, source_annotation) triple.
"""

from __future__ import annotations

from academic_pipeline.writing.citation_grounding import (
    ParsedCitation,
    parse_citations,
)


class TestSingleCitation:
    def test_single_bracketed_citation(self) -> None:
        text = """# Introduction

The Technology Acceptance Model posits two adoption drivers [@s007].
"""
        results = parse_citations(text)
        assert len(results) == 1
        cite = results[0]
        assert cite.citation_id == "s007"
        assert cite.section == "Introduction"
        assert "Technology Acceptance Model" in cite.claim_text
        assert cite.claim_text.endswith(".")

    def test_narrative_citation(self) -> None:
        """`@s007` (no brackets) is pandoc's narrative form: 'Davis [-@s007] showed...'."""
        text = """# Introduction

@s007 introduced the Technology Acceptance Model.
"""
        results = parse_citations(text)
        assert len(results) == 1
        assert results[0].citation_id == "s007"


class TestGroupedCitations:
    def test_semicolon_group_yields_one_usage_per_id(self) -> None:
        text = """# Background

Multiple studies report low adoption [@s002; @s003; @s004].
"""
        results = parse_citations(text)
        ids = [c.citation_id for c in results]
        assert ids == ["s002", "s003", "s004"]
        # All three share the same surrounding sentence
        assert len({c.claim_text for c in results}) == 1

    def test_locator_suffix_is_stripped(self) -> None:
        """`[@s007, p. 23]` — the locator (`, p. 23`) is part of the citation, not a new id."""
        text = """# Discussion

As shown earlier [@s007, p. 23], adoption is low.
"""
        results = parse_citations(text)
        assert len(results) == 1
        assert results[0].citation_id == "s007"


class TestSectionTracking:
    def test_section_changes_with_h1(self) -> None:
        text = """# Introduction

Claim one [@s001].

# Methodology

Claim two [@s002].
"""
        results = parse_citations(text)
        sections = {c.citation_id: c.section for c in results}
        assert sections == {"s001": "Introduction", "s002": "Methodology"}

    def test_h2_overrides_section(self) -> None:
        """Section tracking uses the most recent heading at any level."""
        text = """# Methodology

## Survey Design

Items adapted from [@s002].
"""
        results = parse_citations(text)
        assert results[0].section == "Survey Design"

    def test_text_before_any_heading_uses_blank_section(self) -> None:
        text = """Some preamble [@s001].
"""
        results = parse_citations(text)
        assert len(results) == 1
        assert results[0].section == ""


class TestFrontmatterAndCodeBlocks:
    def test_yaml_frontmatter_is_skipped(self) -> None:
        """Pandoc-style YAML frontmatter must not contribute citations."""
        text = """---
title: "Example"
abstract: |
  This abstract mentions [@s999] but we don't ground frontmatter.
---

# Introduction

Real claim [@s007].
"""
        results = parse_citations(text)
        ids = [c.citation_id for c in results]
        assert ids == ["s007"]

    def test_fenced_code_blocks_are_skipped(self) -> None:
        """Citations inside ```...``` are literal text, not real citations."""
        text = """# Introduction

Real claim [@s007].

```python
# This is not a real citation: [@s999]
```

Another real claim [@s002].
"""
        results = parse_citations(text)
        ids = [c.citation_id for c in results]
        assert ids == ["s007", "s002"]


class TestMultipleCitationsInOneSentence:
    def test_two_separate_brackets_in_one_sentence(self) -> None:
        text = """# Discussion

This finding aligns with prior work [@s002] though contrast with [@s009] suggests nuance.
"""
        results = parse_citations(text)
        ids = [c.citation_id for c in results]
        assert ids == ["s002", "s009"]
        # Both attached to the same sentence
        assert results[0].claim_text == results[1].claim_text


class TestRealisticParagraph:
    def test_introduction_paragraph_from_run_0511(self) -> None:
        """Realistic excerpt: the first paragraph of run-0511-2107's Introduction.

        Three citations, all bracketed, two of them in a single grouped citation.
        """
        text = """# Introduction

Data science workflows typically involve exploratory programming [@s002].
Unlike traditional development, these workflows prioritize rapid prototyping
over engineering practices [@s003; @s004].
"""
        results = parse_citations(text)
        ids = [c.citation_id for c in results]
        assert ids == ["s002", "s003", "s004"]
        assert all(c.section == "Introduction" for c in results)


# The ParsedCitation dataclass should be hashable-equivalent
# (just a sanity check on the dataclass shape used by parse_citations)
class TestParsedCitationShape:
    def test_parsed_citation_carries_id_text_section(self) -> None:
        cite = ParsedCitation(citation_id="s007", claim_text="claim.", section="Intro")
        assert cite.citation_id == "s007"
        assert cite.claim_text == "claim."
        assert cite.section == "Intro"
