"""resolve_citations_to_pandoc emits ``[@key]`` for pandoc citeproc/natbib."""
from __future__ import annotations

from academic_pipeline.runtime.citation_resolver import resolve_citations_to_pandoc


def test_single_known_key_rewritten() -> None:
    out = resolve_citations_to_pandoc("see [smith2020] for", {"smith2020": 1})
    assert out == "see [@smith2020] for"


def test_unknown_key_left_alone() -> None:
    """Numeric brackets, regulation IDs, etc. are not citations — leave them."""
    out = resolve_citations_to_pandoc("see [1] and [NCT12345]", {"smith2020": 1})
    assert out == "see [1] and [NCT12345]"


def test_multi_key_group_uses_pandoc_semicolon_format() -> None:
    out = resolve_citations_to_pandoc(
        "see [smith2020,jones2021]",
        {"smith2020": 1, "jones2021": 2},
    )
    assert out == "see [@smith2020; @jones2021]"


def test_adjacent_known_keys_merged() -> None:
    out = resolve_citations_to_pandoc(
        "[smith2020][jones2021]",
        {"smith2020": 1, "jones2021": 2},
    )
    assert out == "[@smith2020; @jones2021]"


def test_mixed_known_and_unknown_not_merged() -> None:
    out = resolve_citations_to_pandoc(
        "[smith2020][unknown]",
        {"smith2020": 1},
    )
    # First gets rewritten, second left alone — no false merging.
    assert out == "[@smith2020][unknown]"
