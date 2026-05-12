"""Author-block emission contract.

Pinned because the prior pipeline produced an embarrassing
``Author, Affiliation TBD`` byline on the first page of every paper —
the intake agent fabricated a placeholder Author and the renderer dutifully
emitted it. The fix has two layers:

1. Intake agent now leaves ``authors=[]`` when no real author info is
   supplied (covered by the YAML spec change in writing/specs/intake.yaml).
2. SectionMergerNode no longer falls back to ``Author(name="Anonymous", ...)``
   when ``paper_config.authors`` is empty — it propagates the empty list.

This file pins the renderer's contract so that:
  - empty authors → NO ``author:`` line in YAML frontmatter (pandoc emits
    a clean empty title block instead of "Author, Affiliation TBD")
  - real authors → ``author:`` line with all entries
"""
from __future__ import annotations

from academic_pipeline.models.shared import Author, Reference
from academic_pipeline.models.writing import PaperDraft, Section
from academic_pipeline.runtime.paper_renderer import render_markdown


def _draft(authors: list[Author]) -> PaperDraft:
    return PaperDraft(
        title="Test",
        abstract="Test abstract.",
        authors=authors,
        keywords=["a", "b", "c"],
        sections=[
            Section(heading="Intro", level=1, content="Body.", word_count=1, citation_count=0),
        ],
        references=[Reference(id="x2020", full_citation="X. (2020).")],
        total_word_count=1,
    )


def test_empty_authors_emits_no_author_line() -> None:
    """When authors is empty, the YAML frontmatter must NOT include
    ``author:`` — otherwise pandoc renders an empty/garbage byline."""
    md = render_markdown(_draft(authors=[]))
    # The YAML block runs from the first --- to the second ---.
    yaml_block = md.split("---", 2)[1]
    assert "author:" not in yaml_block, (
        "Empty author list must produce NO 'author:' YAML key — found one. "
        "The fallback shouldn't fabricate a byline."
    )


def test_real_authors_emit_author_line() -> None:
    md = render_markdown(_draft(authors=[
        Author(name="Jane Doe", affiliation="ACME University"),
    ]))
    yaml_block = md.split("---", 2)[1]
    assert "author:" in yaml_block
    assert "Jane Doe" in yaml_block
    assert "ACME University" in yaml_block


def test_no_tbd_or_anonymous_placeholders_anywhere() -> None:
    """Defense-in-depth: even if upstream slips, the renderer must
    never emit the historic placeholder strings."""
    md = render_markdown(_draft(authors=[]))
    assert "Affiliation TBD" not in md
    assert "Anonymous" not in md
    assert "Independent Researcher" not in md
