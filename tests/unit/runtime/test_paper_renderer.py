"""Tests for paper_renderer citation conversion and LaTeX rendering."""

from __future__ import annotations

import pytest

from academic_pipeline.models.shared import (
    Author,
    Reference,
)
from academic_pipeline.models.writing import (
    PaperDraft,
    Section,
)
from academic_pipeline.runtime.paper_renderer import (
    _convert_citations,
    _md_to_latex,
    render_latex,
)


class TestConvertCitations:
    def test_single_citation(self) -> None:
        assert _convert_citations(
            "text [sculley2015] more", {"sculley2015": 1}
        ) == r"text \cite{sculley2015} more"

    def test_adjacent_citations_merged(self) -> None:
        assert _convert_citations(
            "[breck2017][sculley2015]", {"breck2017": 1, "sculley2015": 2}
        ) == r"\cite{breck2017,sculley2015}"

    def test_spaced_adjacent_citations_merged(self) -> None:
        assert _convert_citations(
            "[breck2017] [sculley2015]", {"breck2017": 1, "sculley2015": 2}
        ) == r"\cite{breck2017,sculley2015}"

    def test_narrative_citation_preserved(self) -> None:
        assert _convert_citations(
            "Sculley et al. [sculley2015] found", {"sculley2015": 1}
        ) == r"Sculley et al. \cite{sculley2015} found"

    def test_numbered_list_not_converted(self) -> None:
        assert _convert_citations("[1] first item", {}) == "[1] first item"

    def test_section_ref_not_converted(self) -> None:
        assert _convert_citations("see Section [IV]", {}) == "see Section [IV]"

    def test_no_citations(self) -> None:
        assert _convert_citations("plain text without citations", {}) == "plain text without citations"

    def test_citation_with_letter_suffix(self) -> None:
        assert _convert_citations(
            "[smith2020a]", {"smith2020a": 1}
        ) == r"\cite{smith2020a}"

    def test_multiple_separate_citations(self) -> None:
        assert _convert_citations(
            "first [a2020] then [b2021] end", {"a2020": 1, "b2021": 2}
        ) == r"first \cite{a2020} then \cite{b2021} end"

    def test_four_adjacent_citations_merged(self) -> None:
        assert _convert_citations(
            "[a2020][b2021][c2022][d2023]",
            {"a2020": 1, "b2021": 2, "c2022": 3, "d2023": 4},
        ) == r"\cite{a2020,b2021,c2022,d2023}"


class TestRenderLatexCitations:
    def _make_draft(
        self, content: str, references: list[Reference] | None = None
    ) -> PaperDraft:
        return PaperDraft(
            title="Test Paper",
            abstract="Abstract text.",
            authors=[Author(name="Test Author", affiliation="Test Univ")],
            keywords=["test", "unit", "example"],
            sections=[
                Section(
                    heading="Intro",
                    level=1,
                    content=content,
                    word_count=10,
                    citation_count=1,
                )
            ],
            references=references
            or [
                Reference(
                    id="smith2020",
                    full_citation="Smith (2020). Test Paper.",
                )
            ],
            total_word_count=10,
        )

    def test_citation_converted_to_cite_command(self) -> None:
        tex = render_latex(self._make_draft("See [smith2020] for details."))
        assert r"\cite{smith2020}" in tex
        assert "[smith2020]" not in tex

    def test_bibitem_uses_reference_id(self) -> None:
        tex = render_latex(self._make_draft("Text [smith2020]."))
        assert r"\bibitem{smith2020}" in tex

    def test_cite_not_escaped(self) -> None:
        tex = render_latex(self._make_draft("Text [smith2020]."))
        assert r"\cite\{" not in tex


class TestRenderLatexBibliographyAware:
    def test_unknown_token_not_converted(self) -> None:
        draft = PaperDraft(
            title="t",
            abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[
                Section(
                    heading="Body",
                    level=1,
                    content="See [smith2020]. Trial [NCT04567890] is unrelated.",
                    word_count=10,
                    citation_count=1,
                )
            ],
            references=[Reference(id="smith2020", full_citation="Smith (2020).")],
            total_word_count=10,
        )
        tex = render_latex(draft)
        assert r"\cite{smith2020}" in tex
        assert "[NCT04567890]" in tex  # untouched
        assert r"\cite{NCT04567890}" not in tex


class TestSentinelCollisionGuard:
    def test_md_to_latex_rejects_sentinel_collision(self) -> None:
        with pytest.raises(RuntimeError, match="cite-protection sentinel"):
            _md_to_latex("text containing ZZCITEPROTECTZZ in source", {})


class TestHeadingStrip:
    def test_strip_simple_numeric_prefix(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("1. Introduction") == "Introduction"

    def test_strip_dotted_numeric_prefix(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("2.1 The No-Free-Lunch Theorem") == "The No-Free-Lunch Theorem"

    def test_strip_section_keyword(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("Section 3. Methods") == "Methods"

    def test_strip_no_dot_after_number(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("3 Methods") == "Methods"

    def test_no_numeric_prefix_unchanged(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("Introduction") == "Introduction"

    def test_number_in_middle_preserved(self) -> None:
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        # Only LEADING numeric prefix should be stripped
        assert _strip_heading_number("Methods for COVID-19") == "Methods for COVID-19"

    def test_just_number_with_trailing_space_falls_back(self) -> None:
        """A heading that's just a number with trailing space should NOT
        strip to empty — fall back to the original so the malformed input
        is visible downstream."""
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("1. ") == "1. "
        assert _strip_heading_number("Section 3. ") == "Section 3. "

    def test_just_number_no_trailing_space_unchanged(self) -> None:
        """Without trailing whitespace, the regex doesn't even match."""
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("1.") == "1."

    def test_strip_multi_dot_dotted_prefix(self) -> None:
        """Multi-dot prefixes like 4.1.2 should strip cleanly."""
        from academic_pipeline.runtime.paper_renderer import _strip_heading_number
        assert _strip_heading_number("4.1.2 Sub-sub-heading") == "Sub-sub-heading"
        assert _strip_heading_number("1.2.3.4 Deep section") == "Deep section"

    def test_render_markdown_strips_numbered_headings(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[
                Section(heading="1. Introduction", level=1, content="x", word_count=1, citation_count=0),
                Section(heading="2.1 Background", level=2, content="x", word_count=1, citation_count=0),
                Section(heading="Section 3. Methods", level=1, content="x", word_count=1, citation_count=0),
            ],
            references=[], total_word_count=3,
        )
        md = render_markdown(d)
        assert "# Introduction" in md
        assert "## Background" in md
        assert "# Methods" in md
        assert "# 1. Introduction" not in md
        assert "## 2.1 Background" not in md

    def test_render_latex_strips_numbered_headings(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_latex

        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[
                Section(heading="1. Introduction", level=1, content="x", word_count=1, citation_count=0),
            ],
            references=[], total_word_count=1,
        )
        tex = render_latex(d)
        assert r"\section{Introduction}" in tex
        assert r"\section{1. Introduction}" not in tex


class TestFigureMarkerSubstitution:
    def test_marker_replaced_with_image_when_artifact_present(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            Figure,
            FigurePackage,
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(
            figures=[Figure(
                figure_number=1, caption="Caption text", code_language="python",
                code="pass", data_source="", placement="",
            )],
            tables=[],
        )
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(
                heading="Results", level=1,
                content="As shown in [FIGURE: 1], performance improves.",
                word_count=8, citation_count=0,
            )],
            references=[], total_word_count=8,
        )
        md = render_markdown(d, figure_package=pkg)
        # Alt-text is the figure's actual caption (used as pandoc \caption{})
        # — historically this was hard-coded to "Figure N" which produced
        # nonsense PDF captions like "Fig. 2. Figure 3".
        assert "![Caption text](figures/figure_01.png)" in md
        assert "[FIGURE: 1]" not in md

    def test_marker_with_no_matching_figure_left_alone(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            FigurePackage,
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(figures=[], tables=[])
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(
                heading="Results", level=1,
                content="See [FIGURE: 99] (missing).",
                word_count=4, citation_count=0,
            )],
            references=[], total_word_count=4,
        )
        md = render_markdown(d, figure_package=pkg)
        # Marker stays so the gap is visible to the author
        assert "[FIGURE: 99]" in md

    def test_no_figure_package_marker_unchanged(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(
                heading="Results", level=1,
                content="See [FIGURE: 1].",
                word_count=3, citation_count=0,
            )],
            references=[], total_word_count=3,
        )
        # No figure_package passed
        md = render_markdown(d)
        assert "[FIGURE: 1]" in md


class TestTableRendering:
    def test_table_with_rows_renders_markdown_table(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            FigurePackage,
            PaperDraft,
            Section,
            Table,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(
            figures=[],
            tables=[Table(
                table_number="1",
                title="Study Characteristics",
                caption="Table 1. Study characteristics for the 25 included studies.",
                placement="Section 4.1",
                headers=["Study", "N", "AUROC"],
                rows=[
                    ["Alaa 2019", "423604", "0.762"],
                    ["Imrie 2023", "12000", "0.748"],
                ],
            )],
        )
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(heading="Results", level=1, content="See Table 1.", word_count=2, citation_count=0)],
            references=[], total_word_count=2,
        )
        md = render_markdown(d, figure_package=pkg)
        # Pandoc auto-prepends "Table N:" to the caption; we don't
        # bake "**Table N.**" ourselves anymore (it duplicated the label).
        assert "Study Characteristics" in md
        assert ": Study Characteristics" in md  # pandoc caption line
        assert "| Study | N | AUROC |" in md
        assert "| Alaa 2019 | 423604 | 0.762 |" in md
        # NO fake placeholder rows
        assert "| (see narrative) |" not in md

    def test_table_without_rows_renders_cross_reference(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            FigurePackage,
            PaperDraft,
            Section,
            Table,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(
            figures=[],
            tables=[Table(
                table_number="2",
                title="Study Characteristics",
                caption="Table 2.",
                placement="§4.1",
                headers=[],
                rows=[],
            )],
        )
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(heading="Results", level=1, content="See Table 2.", word_count=2, citation_count=0)],
            references=[], total_word_count=2,
        )
        md = render_markdown(d, figure_package=pkg)
        # No row data → cross-reference fallback, NOT a pandoc table caption.
        assert "Study Characteristics" in md
        assert "see narrative" in md.lower() or "reported in" in md.lower()
        # Honest cross-reference, NOT fake rows
        assert ("see narrative" in md.lower() or "reported in" in md.lower())
        assert "| (see narrative) |" not in md
        # Should NOT have a markdown table delimiter line either
        assert "|---|" not in md or md.count("|---|") == 0

    def test_table_without_placement_uses_default_phrase(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            FigurePackage,
            PaperDraft,
            Section,
            Table,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(
            figures=[],
            tables=[Table(
                table_number="3",
                title="Title Only",
                caption="",
                placement="",
                headers=[],
                rows=[],
            )],
        )
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(heading="Results", level=1, content="x", word_count=1, citation_count=0)],
            references=[], total_word_count=1,
        )
        md = render_markdown(d, figure_package=pkg)
        # No placement -> fall back to a default (e.g. "the narrative" or "the discussion")
        assert "Title Only" in md

    def test_no_tables_no_table_section(self) -> None:
        from academic_pipeline.models.shared import Author
        from academic_pipeline.models.writing import (
            FigurePackage,
            PaperDraft,
            Section,
        )
        from academic_pipeline.runtime.paper_renderer import render_markdown

        pkg = FigurePackage(figures=[], tables=[])
        d = PaperDraft(
            title="t", abstract="a",
            authors=[Author(name="x", affiliation="y")],
            keywords=["k1", "k2", "k3"],
            sections=[Section(heading="Results", level=1, content="x", word_count=1, citation_count=0)],
            references=[], total_word_count=1,
        )
        md = render_markdown(d, figure_package=pkg)
        # No tables present - no Table block emitted
        assert "**Table" not in md
