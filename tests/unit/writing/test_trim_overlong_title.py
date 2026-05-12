"""Title truncation guard in SectionMergerNode.

Pinned because the structure_architect agent has historically produced
titles like:
  "When No Algorithm Wins: A Multi-Layer Benchmark of K-means,
   Hierarchical, DBSCAN, and GMM Clustering for Pharmacy Store
   Segmentation Reveals Index-Actionability Divergence on
   Weakly-Separable Retail Data"
(45 words / 4-5 typeset lines on the first page of the rendered PDF).

The structure_architect.yaml prompt now forbids titles >15 words; this
runtime guard catches the regression if a future model run ignores the
prompt.
"""
from __future__ import annotations

from academic_pipeline.writing.graph import _trim_overlong_title


def test_short_title_passes_through_unchanged() -> None:
    short = "Large Language Models Enable Few-Shot Clustering"
    assert _trim_overlong_title(short) == short


def test_borderline_15_words_passes() -> None:
    fifteen_words = " ".join(["word"] * 15)
    assert _trim_overlong_title(fifteen_words) == fifteen_words


def test_overlong_title_with_colon_cut_at_colon() -> None:
    """Prefer the natural pre-colon clause over a hard word slice."""
    bad = (
        "Index-Actionability Divergence: A Multi-Layer Benchmark of K-means, "
        "Hierarchical, DBSCAN, and GMM Clustering for Pharmacy Store "
        "Segmentation on Weakly-Separable Retail Data"
    )
    out = _trim_overlong_title(bad)
    assert out == "Index-Actionability Divergence"


def test_overlong_title_with_emdash_cut_at_emdash() -> None:
    bad = (
        "When the Silhouette Winner Loses on Actionability — "
        "A Multi-Layer Benchmark across K-means, Ward, GMM, DBSCAN, "
        "and HDBSCAN on Weakly-Separable Retail Data"
    )
    out = _trim_overlong_title(bad)
    assert out == "When the Silhouette Winner Loses on Actionability"


def test_runaway_title_no_natural_break_hard_sliced() -> None:
    """When there's no colon/em-dash/period within range, fall back to
    a word-bounded slice at _MAX_TITLE_WORDS."""
    bad = " ".join(f"word{i}" for i in range(50))
    out = _trim_overlong_title(bad)
    assert len(out.split()) == 15
    assert out.startswith("word0 word1 ")


def test_actual_offending_title_from_production_pdf_is_trimmed() -> None:
    """The exact 45-word title from output/latest/02-writing/artifacts/
    paper_p1validated.pdf — must be cut to a publishable length."""
    bad = (
        "When No Algorithm Wins: A Multi-Layer Benchmark of K-means, "
        "Hierarchical, DBSCAN, and GMM Clustering for Pharmacy Store "
        "Segmentation Reveals Index-Actionability Divergence on "
        "Weakly-Separable Retail Data"
    )
    out = _trim_overlong_title(bad)
    assert out == "When No Algorithm Wins"
    assert len(out.split()) <= 15
