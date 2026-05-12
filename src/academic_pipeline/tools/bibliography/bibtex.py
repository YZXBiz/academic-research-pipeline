"""BibTeX generator tools for academic bibliography metadata.

Convert structured bibliography metadata dicts into BibTeX @article entries
and assemble multi-entry .bib file content.
"""

from __future__ import annotations

import re
from typing import Any


# LaTeX special characters that must be escaped inside BibTeX field values.
_LATEX_SPECIAL = re.compile(r"([&%#_$~^])")


def _escape_bibtex(text: str) -> str:
    """Escape special LaTeX characters in a BibTeX field value.

    Args:
        text: Raw text that may contain characters special to LaTeX.

    Returns:
        Text with &, %, #, _, $, ~, and ^ prefixed by a backslash.
    """
    return _LATEX_SPECIAL.sub(r"\\\1", text)


def _make_citation_key(metadata: dict[str, Any]) -> str:
    """Derive a citation key from metadata in ``surname + year`` format.

    The surname is extracted from the first entry in *author* (or *authors*). If no author is available the key falls
    back to ``unknown<year>``.

    Args:
        metadata: Bibliography metadata dict.

    Returns:
        A lowercase citation key such as ``vaswani2017``.
    """
    year = str(metadata.get("year", ""))
    authors: str | list[str] = metadata.get("author") or metadata.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]

    if authors:
        first_author = authors[0]
        # Handle "Family, Given" format
        surname = first_author.split(",")[0].strip()
        # Handle "Given Family" format (no comma)
        if " " in surname and "," not in first_author:
            surname = first_author.split()[-1]
    else:
        surname = "unknown"

    # Strip non-alpha chars — BibTeX keys cannot contain spaces or special chars
    clean_surname = re.sub(r"[^a-z]", "", surname.lower())
    return (clean_surname or "unknown") + year


def generate_bibtex_entry(metadata: dict[str, Any]) -> str:
    """Convert a single bibliography metadata dict to a BibTeX ``@article`` entry.

    Supported metadata keys: author/authors, title, year, journal, volume, number (issue), pages, doi, publisher.

    Args:
        metadata: Dictionary of bibliographic fields.

    Returns:
        A formatted BibTeX ``@article{...}`` string.
    """
    key = metadata.get("id") or _make_citation_key(metadata)

    # Normalise author list to a single BibTeX "and"-separated string.
    authors: str | list[str] = metadata.get("author") or metadata.get("authors") or []
    author_str = " and ".join(authors) if isinstance(authors, list) else authors

    # Map metadata keys to BibTeX field names.
    field_map: list[tuple[str, str]] = [
        ("author", author_str),
        ("title", str(metadata.get("title", ""))),
        ("year", str(metadata.get("year", ""))),
        ("journal", str(metadata.get("journal", ""))),
        ("volume", str(metadata.get("volume", ""))),
        ("number", str(metadata.get("number") or metadata.get("issue", ""))),
        ("pages", str(metadata.get("pages", ""))),
        ("doi", str(metadata.get("doi", ""))),
        ("publisher", str(metadata.get("publisher", ""))),
    ]

    lines: list[str] = [f"@article{{{key},"]
    for field_name, value in field_map:
        if value:
            escaped = _escape_bibtex(value)
            lines.append(f"  {field_name} = {{{escaped}}},")
    lines.append("}")

    return "\n".join(lines)


def generate_bibtex_file(entries: list[dict[str, Any]]) -> str:
    """Join multiple metadata dicts into a complete BibTeX file string.

    Handles duplicate citation keys by appending letter suffixes (a, b, c...).

    Args:
        entries: List of bibliography metadata dicts.

    Returns:
        BibTeX entries separated by double newlines, or an empty string
        when *entries* is empty.
    """
    if not entries:
        return ""

    # Track seen keys and deduplicate with letter suffixes
    seen_keys: dict[str, int] = {}
    results: list[str] = []
    for entry_meta in entries:
        bibtex = generate_bibtex_entry(entry_meta)
        key = entry_meta.get("id") or _make_citation_key(entry_meta)
        count = seen_keys.get(key, 0)
        seen_keys[key] = count + 1
        if count > 0:
            # Replace the first occurrence of the key with the suffixed version
            suffix = chr(ord("a") + count)
            bibtex = bibtex.replace(f"@article{{{key},", f"@article{{{key}{suffix},", 1)
        results.append(bibtex)
    return "\n\n".join(results)
