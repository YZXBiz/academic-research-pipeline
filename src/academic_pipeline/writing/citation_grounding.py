"""Citation extraction helpers for the citation-grounding agent.

Walks a paper draft Markdown and emits one record per `[@sNNN]` (or
narrative `@sNNN`) occurrence, paired with the sentence containing the
citation and the active section heading.

Handles three forms of citation:
  - bracketed:           `[@s007]`            -> one usage
  - bracketed-grouped:   `[@s001; @s002]`     -> two usages, same claim
  - bracketed-locator:   `[@s007, p. 23]`     -> one usage (locator ignored)
  - narrative:           `@s007 showed that…` -> one usage

Skips:
  - YAML frontmatter (between leading `---` ... `---`)
  - Fenced code blocks (between ```...```)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from academic_pipeline.models.research import Bibliography


__all__ = [
    "GroundingPair",
    "ParsedCitation",
    "build_grounding_pairs",
    "parse_citations",
]


# A citation key is `@` followed by an identifier. We use a conservative
# pattern (alphanumerics + underscores) since pipeline bibliographies use
# `sNNN`-style keys. The negative-lookbehind on `\w` filters out email
# addresses like `user@example` (the `@` after `user` would otherwise match).
_CITATION_RE = re.compile(r"(?<!\w)@([A-Za-z][A-Za-z0-9_]*)")
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"^```")
# Sentence boundary: period/!/? followed by whitespace and an uppercase or `[@` start.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[@])")


@dataclass(frozen=True)
class ParsedCitation:
    """One citation occurrence in a paper draft."""

    citation_id: str
    claim_text: str
    section: str


@dataclass(frozen=True)
class GroundingPair:
    """A parsed citation joined with the cited source's bibliographic context.

    This is the input format the citation_grounding agent receives — it has
    every signal needed to ask "does the source actually support this claim?"
    without any additional lookups.
    """

    citation_id: str
    claim_text: str
    section: str
    source_title: str
    source_year: int
    source_annotation: str


def build_grounding_pairs(
    bibliography: Bibliography, citations: list[ParsedCitation]
) -> list[GroundingPair]:
    """Join parsed citations with their bibliography source annotations.

    Citations whose `citation_id` is missing from the bibliography are dropped
    — orphan-citation detection is `citation_compliance`'s job, not ours.
    """
    by_id = {s.id: s for s in bibliography.sources}
    out: list[GroundingPair] = []
    for cite in citations:
        source = by_id.get(cite.citation_id)
        if source is None:
            continue
        out.append(
            GroundingPair(
                citation_id=cite.citation_id,
                claim_text=cite.claim_text,
                section=cite.section,
                source_title=source.title,
                source_year=source.year,
                source_annotation=source.annotation,
            )
        )
    return out


def _strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block, if present."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def _strip_fenced_code(text: str) -> str:
    """Drop fenced-code-block spans so citation-like tokens inside them are ignored."""
    out: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _section_at_offset(text: str, offset: int) -> str:
    """Return the heading title most recently introduced at-or-before `offset`."""
    last = ""
    for match in _HEADING_RE.finditer(text):
        if match.start() > offset:
            break
        last = match.group(1).strip()
    return last


def _split_sentences(paragraph: str) -> list[str]:
    """Split a paragraph into trimmed sentences."""
    pieces = _SENTENCE_SPLIT_RE.split(paragraph)
    return [s.strip() for s in pieces if s.strip()]


def parse_citations(text: str) -> list[ParsedCitation]:
    """Extract every pandoc-style citation occurrence from a paper draft.

    Returns one ParsedCitation per (citation_id, occurrence) pair — i.e. a
    bracketed group like `[@s001; @s002]` yields two entries that share the
    same `claim_text` and `section`.
    """
    cleaned = _strip_fenced_code(_strip_frontmatter(text))

    results: list[ParsedCitation] = []
    paragraphs_with_offsets: list[tuple[int, str]] = []
    cursor = 0
    for paragraph in cleaned.split("\n\n"):
        paragraphs_with_offsets.append((cursor, paragraph))
        cursor += len(paragraph) + 2  # +2 for the "\n\n" separator

    for para_offset, paragraph in paragraphs_with_offsets:
        if paragraph.lstrip().startswith("#"):
            # Heading-only paragraph contributes no citations.
            continue
        for sentence in _split_sentences(paragraph):
            ids_in_sentence = [m.group(1) for m in _CITATION_RE.finditer(sentence)]
            if not ids_in_sentence:
                continue
            sentence_local = paragraph.find(sentence)
            section = _section_at_offset(cleaned, para_offset + max(sentence_local, 0))
            results.extend(
                ParsedCitation(citation_id=cid, claim_text=sentence, section=section)
                for cid in ids_in_sentence
            )

    return results
