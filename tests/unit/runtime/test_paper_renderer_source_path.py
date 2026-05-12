"""_substitute_figure_markers should prefer Figure.source_path's basename when set."""
from __future__ import annotations

from pathlib import Path

from academic_pipeline.models.writing import Figure, FigurePackage
from academic_pipeline.runtime.paper_renderer import _substitute_figure_markers


def _pkg(*figs: Figure) -> FigurePackage:
    """Build a minimal FigurePackage. FigurePackage only requires `figures`."""
    return FigurePackage(figures=list(figs))


def test_source_path_basename_used_when_set() -> None:
    fig = Figure(
        figure_number=1,
        caption="Silhouette vs k.",
        source_path=Path("/abs/path/figures/figure_01_silhouette_vs_k.png"),
    )
    out = _substitute_figure_markers("Some text. [FIGURE: 1] More.", _pkg(fig))
    # Basename only — LatexCompilerNode copies PNGs into build_dir/figures/.
    assert "figures/figure_01_silhouette_vs_k.png" in out
    # Should NOT contain the absolute path (pandoc cwd-relative).
    assert "/abs/path/" not in out


def test_legacy_convention_when_source_path_none() -> None:
    """Snapshots without source_path must still resolve via figures/figure_NN.png."""
    fig = Figure(figure_number=2, caption="Bootstrap ARI.")  # no source_path
    out = _substitute_figure_markers("[FIGURE: 2]", _pkg(fig))
    assert "figures/figure_02.png" in out


def test_unknown_figure_number_passes_through_unchanged() -> None:
    out = _substitute_figure_markers("[FIGURE: 99]", _pkg())
    assert out == "[FIGURE: 99]"


def test_pdf_source_path_renders_through_unchanged() -> None:
    """The renderer must handle .pdf basename, not just .png — the
    publication-quality matplotlib style emits PDFs, not PNGs."""
    fig = Figure(
        figure_number=1,
        caption="Silhouette vs k.",
        source_path=Path("/abs/figures/figure_01_silhouette_vs_k.pdf"),
    )
    out = _substitute_figure_markers("[FIGURE: 1]", _pkg(fig))
    # Renderer should emit the basename verbatim — pandoc + tectonic both
    # accept \includegraphics{path.pdf} for vector inclusion.
    assert "figures/figure_01_silhouette_vs_k.pdf" in out
    # Not blindly .png-suffixing.
    assert ".png" not in out
