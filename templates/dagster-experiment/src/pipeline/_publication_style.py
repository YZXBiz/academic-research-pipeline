"""Publication-quality matplotlib style for paper figures.

The default matplotlib output (sans-serif, 8pt labels, PNG raster, 8x6 inch)
reads as a Jupyter screenshot in a journal paper. This helper bakes a
publication-quality style that:

  - Uses serif font matching LaTeX body text (no usetex by default — that
    requires a working LaTeX install in the workspace, fragile in CI).
  - Sizes labels at 9-10pt (matches IEEEtran 10pt body text).
  - Sets savefig.format='pdf' so figures are vector (infinite zoom).
  - Sets savefig.dpi=300 as a safety net for any rasterized component.
  - Provides column_width_inches() / page_width_inches() helpers so figures
    are designed at FINAL PRINT SIZE (no \\includegraphics scaling).

Usage in a generated figures.py @asset:

    import matplotlib
    matplotlib.use("Agg")  # headless backend — required for Dagster workers
    import matplotlib.pyplot as plt

    from pipeline._publication_style import apply_pub_style, column_width_inches

    apply_pub_style()  # call ONCE at module import time

    fig, ax = plt.subplots(figsize=(column_width_inches(), 2.5))
    ax.plot(...)
    fig.savefig("figures/figure_01.pdf", bbox_inches="tight")
"""
from __future__ import annotations


PUB_STYLE: dict = {
    # Font — serif to match LaTeX body. No text.usetex (requires LaTeX install).
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    # Lines — paper-thin
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.2,
    "lines.markersize": 4,
    # Ticks — minor off, light direction
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.minor.visible": False,
    "ytick.minor.visible": False,
    # Grid — subtle
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.4,
    # Save — vector PDF, tight bbox, 300 dpi safety net
    "savefig.format": "pdf",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    # Figure background — white (default but explicit)
    "figure.facecolor": "white",
    "axes.facecolor": "white",
}


def apply_pub_style() -> None:
    """Update matplotlib's global rcParams with PUB_STYLE.

    Call ONCE at module-import time inside any @asset that produces figures.
    Idempotent — calling twice is harmless.
    """
    import matplotlib

    matplotlib.rcParams.update(PUB_STYLE)


def column_width_inches() -> float:
    """IEEEtran conference single-column width in inches.

    Measured value for IEEEtran conference class: 3.31314 inches per
    \\the\\columnwidth at fontsize=10pt. Round to 3.3 for clean math.
    """
    return 3.3


def page_width_inches() -> float:
    """IEEEtran conference text width (spans both columns) in inches.

    Used for figures inside table* environments that span both columns.
    Measured ~7.0 inches for IEEEtran conference class.
    """
    return 7.0
