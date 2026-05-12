"""Async citation formatter tools for PydanticAI agents.

Format, validate, and convert academic citation strings across styles
(APA7, Chicago, MLA, IEEE, Vancouver).
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field


class CitationMetadata(BaseModel):
    """Bibliographic metadata for citation formatting."""

    model_config = ConfigDict(populate_by_name=True)

    authors: list[str] = Field(default_factory=list, description="Author names in 'Family, Given' format")
    year: int | str = Field(default="n.d.", description="Publication year")
    title: str = Field(default="Untitled", description="Title of the work")
    journal: str = Field(default="", description="Journal or container title")
    volume: str = Field(default="", description="Volume number")
    issue: str = Field(default="", description="Issue number")
    pages: str = Field(default="", description="Page range (e.g., '1-10')")
    doi: str = Field(default="", description="DOI without URL prefix")
    publisher: str = Field(default="", description="Publisher name")
    source_type: str = Field(
        default="journal-article",
        alias="type",
        description="Source type: journal-article, book, chapter, etc.",
    )


_CitationFormatter = Callable[[CitationMetadata], str]

_FORMATTERS: dict[str, _CitationFormatter] = {}


def _format_author_apa(name: str) -> str:
    """Format an author name into APA-style initials."""
    parts = name.split(", ")
    if len(parts) == 2:
        family, given = parts
        initials = ". ".join(c for c in given if c.isupper()) + "."
        return f"{family}, {initials}"
    return name


def _apa7_author_string(authors: list[str]) -> str:
    """Build the author portion of an APA7 citation."""
    if not authors:
        return "Unknown"
    if len(authors) <= 2:
        return " & ".join(_format_author_apa(a) for a in authors)
    if len(authors) <= 20:
        formatted = [_format_author_apa(a) for a in authors]
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    formatted = [_format_author_apa(a) for a in authors[:19]]
    return ", ".join(formatted) + ", ... " + _format_author_apa(authors[-1])


def _format_apa7(meta: CitationMetadata) -> str:
    """Format a citation string in APA 7th edition style."""
    author_str = _apa7_author_string(meta.authors)
    vol_issue = meta.volume or ""
    if meta.issue:
        vol_issue += f"({meta.issue})"
    page_str = f", {meta.pages}" if meta.pages else ""
    doi_str = f" https://doi.org/{meta.doi}" if meta.doi else ""

    if meta.source_type == "journal-article":
        return f"{author_str} ({meta.year}). {meta.title}. *{meta.journal}*, *{vol_issue}*{page_str}.{doi_str}"
    if meta.source_type == "book":
        return f"{author_str} ({meta.year}). *{meta.title}*. {meta.publisher}.{doi_str}"
    return f"{author_str} ({meta.year}). {meta.title}. {meta.journal or meta.publisher}.{doi_str}"


def _format_chicago(meta: CitationMetadata) -> str:
    """Format a citation string in Chicago style."""
    author_str = ", ".join(meta.authors) if meta.authors else "Unknown"
    doi_str = f" https://doi.org/{meta.doi}." if meta.doi else ""
    if meta.source_type == "journal-article":
        return (
            f'{author_str}. "{meta.title}." *{meta.journal}* {meta.volume}, '
            f"no. {meta.issue} ({meta.year}): {meta.pages}.{doi_str}"
        )
    return f"{author_str}. *{meta.title}*. {meta.publisher}, {meta.year}.{doi_str}"


def _format_mla(meta: CitationMetadata) -> str:
    """Format a citation string in MLA style."""
    if meta.authors:
        author_str = meta.authors[0]
        if len(meta.authors) > 1:
            author_str += ", et al"
    else:
        author_str = "Unknown"
    doi_str = f" doi:{meta.doi}." if meta.doi else ""
    if meta.source_type == "journal-article":
        return (
            f'{author_str}. "{meta.title}." *{meta.journal}*, vol. {meta.volume}, '
            f"no. {meta.issue}, {meta.year}, pp. {meta.pages}.{doi_str}"
        )
    return f"{author_str}. *{meta.title}*. {meta.publisher}, {meta.year}.{doi_str}"


def _format_ieee(meta: CitationMetadata) -> str:
    """Format a citation string in IEEE style."""
    if meta.authors:
        formatted = []
        for a in meta.authors:
            parts = a.split(", ")
            if len(parts) == 2:
                formatted.append(f"{parts[1][0]}. {parts[0]}")
            else:
                formatted.append(a)
        author_str = ", ".join(formatted)
    else:
        author_str = "Unknown"
    if meta.source_type == "journal-article":
        return (
            f'{author_str}, "{meta.title}," *{meta.journal}*, '
            f"vol. {meta.volume}, no. {meta.issue}, pp. {meta.pages}, {meta.year}."
        )
    return f"{author_str}, *{meta.title}*. {meta.publisher}, {meta.year}."


def _format_acl_author(name: str) -> str:
    """Reverse 'Last, First' -> 'First Last' for ACL anthology citations."""
    parts = name.split(", ", 1)
    if len(parts) == 2:
        last, first = parts
        return f"{first} {last}"
    return name


def _acl_author_string(authors: list[str]) -> str:
    """Build the author block of an ACL anthology citation.

    1 author  -> "First Last"
    2 authors -> "First Last and First Last"
    3+        -> "First Last, First Last, and First Last" (Oxford 'and')
    """
    if not authors:
        return "Unknown"
    formatted = [_format_acl_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return " and ".join(formatted)
    return ", ".join(formatted[:-1]) + ", and " + formatted[-1]


def _format_acl(meta: CitationMetadata) -> str:
    """Format a citation in ACL anthology style.

    Per ACL anthology / acl_natbib.bst conventions:
    - Authors: full names (not initials) with 'and' joiner.
    - Year: standalone with period (not parenthesized like APA).
    - Title: no italics.
    - For ``inproceedings``: ``In *Proceedings*, pages X-Y.``
    - For journal-article: ``*Journal*, vol(issue):pages.``
    """
    author_str = _acl_author_string(meta.authors)
    if meta.source_type == "inproceedings":
        page_str = f", pages {meta.pages}" if meta.pages else ""
        return f"{author_str}. {meta.year}. {meta.title}. In *{meta.journal}*{page_str}."
    if meta.source_type == "journal-article":
        vol_issue = meta.volume or ""
        if meta.issue:
            vol_issue += f"({meta.issue})"
        page_str = f":{meta.pages}" if meta.pages else ""
        suffix = f", {vol_issue}{page_str}" if vol_issue or page_str else ""
        return f"{author_str}. {meta.year}. {meta.title}. *{meta.journal}*{suffix}."
    return f"{author_str}. {meta.year}. {meta.title}. {meta.publisher}."


def _format_vancouver(meta: CitationMetadata) -> str:
    """Format a citation string in Vancouver style."""
    if meta.authors:
        formatted = []
        for a in meta.authors[:6]:
            parts = a.split(", ")
            if len(parts) == 2:
                initials = "".join(c for c in parts[1] if c.isupper())
                formatted.append(f"{parts[0]} {initials}")
            else:
                formatted.append(a)
        author_str = ", ".join(formatted)
        if len(meta.authors) > 6:
            author_str += ", et al"
    else:
        author_str = "Unknown"
    if meta.source_type == "journal-article":
        return f"{author_str}. {meta.title}. {meta.journal}. {meta.year};{meta.volume}({meta.issue}):{meta.pages}."
    return f"{author_str}. {meta.title}. {meta.publisher}; {meta.year}."


_FORMATTERS.update(
    {
        "APA7": _format_apa7,
        "Chicago": _format_chicago,
        "MLA": _format_mla,
        "IEEE": _format_ieee,
        "Vancouver": _format_vancouver,
        "ACL": _format_acl,
    }
)


async def format_citation(metadata: CitationMetadata, style: str = "APA7") -> str:
    """Format bibliographic metadata into a citation string in the specified style.

    Args:
        metadata: Structured bibliographic metadata.
        style: One of APA7, Chicago, MLA, IEEE, Vancouver.

    Returns:
        Formatted citation string in the requested style.
    """
    formatter = _FORMATTERS.get(style, _format_apa7)
    return formatter(metadata)


async def validate_citation(citation: str, style: str = "APA7") -> str:
    """Validate a formatted citation string against the specified style rules.

    Returns a list of issues found or 'VALID' if no issues detected.

    Args:
        citation: The formatted citation string to validate.
        style: Citation style to validate against (e.g. "APA7", "IEEE", "Vancouver").

    Returns:
        'VALID' if no issues are detected, otherwise a newline-separated list of issues.
    """
    issues: list[str] = []

    if style == "APA7":
        if "et al." in citation and citation.count(",") < 2:
            issues.append("APA7: 'et al.' only for 3+ authors in-text, full list in references")
        if not any(c in citation for c in ("(", ".")):
            issues.append("APA7: Missing year in parentheses or period at end")
        if "*" not in citation and "_" not in citation:
            issues.append("APA7: Journal/book title should be italicized")
        if "doi:" in citation.lower() and "https://doi.org/" not in citation:
            issues.append("APA7: DOI should be formatted as https://doi.org/...")
    elif style == "IEEE":
        if not citation.strip().endswith("."):
            issues.append("IEEE: Citation must end with a period")
    elif style == "Vancouver":
        if "et al" in citation and citation.count(",") > 6:
            issues.append("Vancouver: List up to 6 authors before et al")

    if not issues:
        return "VALID"
    return "Issues found:\n" + "\n".join(f"- {i}" for i in issues)


async def convert_citation_style(citation: str, from_style: str, to_style: str) -> str:
    """Convert a citation from one style to another.

    Note: This performs heuristic conversion. For best results, use resolve_doi_metadata to get structured data, then
    format_citation.

    Args:
        citation: The citation string in the source style.
        from_style: The current citation style (e.g. "APA7", "IEEE").
        to_style: The target citation style to convert to.

    Returns:
        A guidance message recommending DOI-based conversion for accuracy.
    """
    return (
        f"Heuristic conversion from {from_style} to {to_style} is unreliable. "
        f"For accurate conversion, extract the DOI from the citation, "
        f"use resolve_doi_metadata to get structured bibliographic data, "
        f"then use format_citation with the target style.\n\n"
        f"Original ({from_style}): {citation}"
    )
