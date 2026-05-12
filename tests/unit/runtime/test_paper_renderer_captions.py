"""_substitute_figure_markers must use the figure's caption as alt-text.

Pandoc's implicit_figures extension turns ``![alt](path)`` into a figure
with ``\\caption{alt}``. The previous renderer hard-coded alt-text to
``"Figure N"`` which produced PDF captions like ``Fig. 2. Figure 3``
(see /Users/c839755/Desktop/academic-pipeline/pydanticai/output/latest/02-writing/artifacts/paper_p1validated.pdf
pages 8-11 before this fix).
"""
from __future__ import annotations

from academic_pipeline.models.writing import Figure, FigurePackage
from academic_pipeline.runtime.paper_renderer import _substitute_figure_markers


def _pkg(*figs: Figure) -> FigurePackage:
    return FigurePackage(figures=list(figs))


def test_caption_used_as_alt_text() -> None:
    fig = Figure(
        figure_number=3,
        caption="Distribution of Bootstrap-Resampling Stability (ARI) by Algorithm",
    )
    out = _substitute_figure_markers("As [FIGURE: 3] shows, ...", _pkg(fig))
    assert "![Distribution of Bootstrap-Resampling Stability (ARI) by Algorithm](" in out
    # The literal "Figure 3" placeholder must NOT be the alt text.
    assert "![Figure 3](" not in out


def test_leading_figure_label_stripped_to_avoid_duplication() -> None:
    """Captions that already start with 'Figure N:' must not produce
    'Figure 1: Figure 1: blah' in the rendered PDF (pandoc auto-prepends
    the label)."""
    fig = Figure(figure_number=1, caption="Figure 1: Pipeline overview.")
    out = _substitute_figure_markers("[FIGURE: 1]", _pkg(fig))
    assert "![Pipeline overview.](" in out
    assert "Figure 1: Figure 1" not in out


def test_leading_fig_dot_label_also_stripped() -> None:
    fig = Figure(figure_number=2, caption="Fig. 2. Bootstrap ARI distribution.")
    out = _substitute_figure_markers("[FIGURE: 2]", _pkg(fig))
    assert "![Bootstrap ARI distribution.](" in out


def test_apa_multiline_label_block_stripped() -> None:
    """visualization_agent emits captions in APA form:
        Figure N
        <blank>
        Short title
        <blank>
        Note. Long descriptive text...
    The leading "Figure N\\n\\n" must be stripped."""
    fig = Figure(
        figure_number=1,
        caption=(
            "Figure 1\n\n"
            "Internal Validity Indices Across Clustering Algorithms\n\n"
            "Note. Silhouette and DB values..."
        ),
    )
    out = _substitute_figure_markers("[FIGURE: 1]", _pkg(fig))
    # Must not start with "Figure 1" (that's the literal label being stripped).
    assert "![Internal Validity Indices" in out
    assert "![Figure 1\n" not in out
    assert "![Figure 1 " not in out


def test_empty_caption_falls_back_to_figure_n() -> None:
    fig = Figure(figure_number=4, caption="")
    out = _substitute_figure_markers("[FIGURE: 4]", _pkg(fig))
    assert "![Figure 4](" in out


def test_brackets_in_caption_escaped() -> None:
    """Markdown image alt-text can't contain unescaped brackets without
    breaking the link parser."""
    fig = Figure(figure_number=1, caption="Bootstrap stability [Hennig 2007] vs ARI.")
    out = _substitute_figure_markers("[FIGURE: 1]", _pkg(fig))
    # The brackets in the caption must be escaped so the markdown
    # parser doesn't treat them as a separate link.
    assert "![Bootstrap stability \\[Hennig 2007\\] vs ARI.](" in out
