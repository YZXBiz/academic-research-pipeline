"""Tables-survive-to-PDF contracts.

Pins the fix for the bug where the visualization agent emitted
2 well-formed Table objects (Table.headers + Table.rows populated)
in figure_package.json, but neither the saved ``paper_draft.md``
artifact nor the rendered PDF contained any tables — the markdown
table syntax was emitted, but:

1. The pandoc lua filter rewrote ``longtable`` → ``table*`` using
   ``\\real{}`` and ``>{...}p{...}`` constructs that need ``array``
   and ``calc`` packages, which weren't loaded → tectonic crashed
   with "Undefined control sequence". (Fix in templates/pandoc/acl-header.tex.)

2. ``sdk/result.py``'s ``save()`` called ``render_markdown(val)``
   without passing ``figure_package``, so the artifact dropped tables
   even when they were in state. (Fix in sdk/result.py.)

3. Unicode operators (``×``, ``≥``, ``±``) inside cells rendered as
   missing-glyph boxes / wrong-glyph (``Œ`` for ``×``) because Times
   Roman lacks them and ``newunicodechar`` substitution wasn't being
   applied to raw row data. (Fix in render_markdown's table loop.)
"""
from __future__ import annotations

from academic_pipeline.models.shared import Author, Reference
from academic_pipeline.models.writing import (
    Figure,
    FigurePackage,
    PaperDraft,
    Section,
    Table,
)
from academic_pipeline.runtime.paper_renderer import render_markdown


def _draft_with_table(table: Table) -> PaperDraft:
    return PaperDraft(
        title="Tables Test",
        abstract="Abstract.",
        authors=[Author(name="A", affiliation="B")],
        keywords=["a", "b", "c"],
        sections=[
            Section(heading="Results", level=1, content="See Table 1.",
                    word_count=3, citation_count=0),
        ],
        references=[Reference(id="x", full_citation="X. (2020).")],
        total_word_count=3,
    )


class TestTableUnicodeMath:
    def test_unicode_times_in_cell_promoted_to_math(self) -> None:
        """``9.5 × 10⁻⁶`` in a cell must become ``$\\times$`` math —
        otherwise Times Roman renders the unicode glyph as 'Œ' in the PDF."""
        t = Table(
            table_number="1", title="Results",
            headers=["Algorithm", "p-value"],
            rows=[["GMM", "9.5 × 10⁻⁶"]],
        )
        md = render_markdown(_draft_with_table(t),
                             figure_package=FigurePackage(figures=[], tables=[t]))
        assert "$\\times$" in md
        # The raw unicode multiplication sign must NOT appear in the
        # markdown table cell — it'd render as 'Œ' in the PDF.
        # (We allow it elsewhere — only assert on the table cell row.)
        assert "9.5 $\\times$ 10" in md or "9.5 × 10" not in md.split("| GMM |")[1].split("|")[1]

    def test_unicode_geq_in_header_promoted(self) -> None:
        t = Table(
            table_number="2", title="Cohorts",
            headers=["Cohort", "n ≥ 100"],
            rows=[["A", "yes"]],
        )
        md = render_markdown(_draft_with_table(t),
                             figure_package=FigurePackage(figures=[], tables=[t]))
        assert "$\\geq$" in md


class TestTableCaptionFormat:
    def test_caption_uses_pandoc_native_syntax(self) -> None:
        """``: caption`` after a pipe table is pandoc's native caption
        syntax — renders as ``\\caption{}`` inside the table env. Without
        this, the title appeared as a standalone paragraph BEFORE the
        table, which on a 2-column layout split into a duplicated title
        in column N and the actual table in column N+1.

        We do NOT prefix the caption with "Table N." — pandoc auto-prepends
        "Table N: " when it builds the caption."""
        t = Table(
            table_number="1", title="Headline Results",
            caption="Internal validity vs actionability uplift.",
            headers=["Algorithm", "Sil"], rows=[["K-means", "0.137"]],
        )
        md = render_markdown(_draft_with_table(t),
                             figure_package=FigurePackage(figures=[], tables=[t]))
        # Pandoc-native caption line directly after the table — and
        # MUST NOT contain a redundant "Table 1." prefix (pandoc adds it).
        assert "\n: Headline Results" in md
        caption_line = next(line for line in md.splitlines() if line.startswith(": "))
        assert "Table 1" not in caption_line

    def test_apa_caption_prefix_stripped_to_avoid_triplication(self) -> None:
        """visualization_agent emits ``caption`` as
        ``Table N\\n\\nTitle\\n\\nNote. body`` (APA form). The label and
        title appear THREE times if not stripped: pandoc's auto-label,
        the APA "Table N" prefix, and the title repeated in caption."""
        t = Table(
            table_number="1",
            title="Algorithm Hyperparameter Grid",
            caption=(
                "Table 1\n\nAlgorithm Hyperparameter Grid\n\n"
                "Note. Selected configurations chosen by within-family criterion."
            ),
            headers=["Algo", "k"], rows=[["K-means", "8"]],
        )
        md = render_markdown(_draft_with_table(t),
                             figure_package=FigurePackage(figures=[], tables=[t]))
        # Title appears exactly once in the caption line.
        caption_line = next(line for line in md.splitlines() if line.startswith(": "))
        assert caption_line.count("Algorithm Hyperparameter Grid") == 1
        # APA label "Table 1" / "Table 1." must NOT appear in caption.
        assert "Table 1" not in caption_line
        # Note. body still present.
        assert "Note. Selected configurations" in caption_line


class TestTableArtifactPlumbing:
    """sdk/result.py must pass figure_package into render_markdown so the
    saved paper_draft.md contains tables, not just the PDF."""

    def test_result_save_includes_tables_in_paper_draft_md(
        self, tmp_path: object,
    ) -> None:
        from pathlib import Path

        from academic_pipeline.sdk.result import PipelineResult

        t = Table(
            table_number="1", title="Headline",
            headers=["Algo", "p"], rows=[["GMM", "0.05"]],
        )
        draft = _draft_with_table(t)
        pkg = FigurePackage(figures=[], tables=[t])

        result = PipelineResult({
            "paper_draft": draft,
            "figure_package": pkg,
            "topic": "test",
            "run_id": "test-run",
            "pipeline_status": "complete",
            "current_stage": "done",
        })

        out = Path(str(tmp_path)) / "saved"
        result.save(out)

        md_path = out / "02-writing" / "artifacts" / "paper_draft.md"
        assert md_path.exists()
        md = md_path.read_text(encoding="utf-8")
        # The table must appear in the saved markdown.
        assert "| Algo | p |" in md
        assert "| GMM | 0.05 |" in md
