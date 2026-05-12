from __future__ import annotations

from pathlib import Path

from academic_pipeline.models.writing import Figure


def test_figure_accepts_source_path() -> None:
    fig = Figure(
        figure_number=1,
        caption="Silhouette vs k for four clustering algorithms.",
        source_path=Path("figures/figure_01_silhouette_vs_k.png"),
    )
    assert fig.source_path == Path("figures/figure_01_silhouette_vs_k.png")


def test_figure_source_path_defaults_none() -> None:
    """Default for source_path is None — legacy figures (code-only) still validate."""
    fig = Figure(
        figure_number=2,
        caption="Bootstrap ARI distributions.",
    )
    assert fig.source_path is None
