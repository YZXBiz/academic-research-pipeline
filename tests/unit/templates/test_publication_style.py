"""Workspace template's _publication_style helper:
- Exports PUB_STYLE rcParams dict targeting serif-font + paper sizing.
- apply_pub_style() updates plt.rcParams.
- column_width_inches() / page_width_inches() return IEEEtran-correct sizes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


_HELPER_PATH = (
    Path(__file__).resolve().parents[3]
    / "templates" / "dagster-experiment" / "src" / "pipeline" / "_publication_style.py"
)


@pytest.fixture
def helper_module():
    """Load _publication_style.py as an importable module from disk."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_publication_style", _HELPER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pub_style_targets_serif_font(helper_module) -> None:
    style = helper_module.PUB_STYLE
    assert style["font.family"] == "serif", (
        "Publication style must use serif font to match LaTeX paper text."
    )


def test_pub_style_uses_publication_font_sizes(helper_module) -> None:
    style = helper_module.PUB_STYLE
    assert style["font.size"] in (9, 10), f"font.size={style['font.size']} unusual for paper figures."
    assert style["axes.labelsize"] in (9, 10)
    assert style["xtick.labelsize"] in (7, 8, 9)


def test_pub_style_uses_savefig_pdf_format(helper_module) -> None:
    style = helper_module.PUB_STYLE
    assert style["savefig.format"] == "pdf", (
        "Default savefig format must be 'pdf' (vector). PNG raster figures "
        "blur on zoom and read as Jupyter screenshots."
    )


def test_pub_style_uses_300_dpi_for_any_raster_fallback(helper_module) -> None:
    style = helper_module.PUB_STYLE
    assert style["savefig.dpi"] >= 300, (
        "Per most journal author guidelines: any rasterized component must "
        "be >= 300 dpi at final print size."
    )


def test_apply_pub_style_updates_rcparams(helper_module) -> None:
    matplotlib = pytest.importorskip(
        "matplotlib",
        reason="matplotlib not installed in main project env (it lives in the "
        "workspace template's deps via autogluon/sklearn).",
    )

    original_family = matplotlib.rcParams["font.family"]
    try:
        helper_module.apply_pub_style()
        family = matplotlib.rcParams["font.family"]
        assert "serif" in family or family == ["serif"] or family == "serif", (
            f"After apply_pub_style(), font.family should include 'serif'. Got: {family!r}"
        )
    finally:
        matplotlib.rcParams["font.family"] = original_family


def test_column_width_inches_matches_ieeetran_conference(helper_module) -> None:
    """IEEEtran conference column width is ~3.31 inches."""
    width = helper_module.column_width_inches()
    assert 3.0 <= width <= 3.6, (
        f"column_width_inches()={width} not in IEEEtran conference range (3.0-3.6 inches)."
    )


def test_page_width_inches_matches_ieeetran_conference(helper_module) -> None:
    """IEEEtran conference text width (spans both columns) is ~7.0 inches."""
    width = helper_module.page_width_inches()
    assert 6.5 <= width <= 7.5, (
        f"page_width_inches()={width} not in IEEEtran conference range (6.5-7.5 inches)."
    )
