"""Deterministic Discussion-vs-Results consistency scanner.

Runs as a pre-flight check inside IntegrityCheckNode, alongside the
placeholder scan. Catches the failure class from run-0511-2107: the
Discussion section confidently interprets quantitative findings ("the
effect size was moderate", "the correlation was robust and persistent")
while the Results section is entirely `[PENDING:]` placeholders — the
paper narrates results it does not have.

The check fires only when BOTH hold:
  1. the Results section still carries `[PENDING:]` markers (unpopulated)
  2. a Discussion-section sentence asserts a magnitude/direction finding

A populated Results section means the Discussion is interpreting real
data — which is exactly what a Discussion is for — so no finding is
emitted. Severity is BLOCKING: a fabricated interpretation is a logical
defect at any phase, not merely an "incomplete draft".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ConsistencyFinding:
    """A Discussion sentence that interprets findings the Results section lacks."""

    claim_text: str
    line: int
    severity: str  # always "BLOCKING"


# Magnitude / strength words applied to an empirical finding.
_MAGNITUDE: Final[str] = (
    r"moderate|strong|weak|large|small|modest|substantial|robust|persistent|significant"
)
# Nouns that name an empirical finding (the thing a Results section reports).
_FINDING_NOUN: Final[str] = (
    r"effect sizes?|effects?|correlations?|associations?|relationships?"
    r"|differences?|predictors?"
)

_MAGNITUDE_RE = re.compile(rf"\b(?:{_MAGNITUDE})\b", re.IGNORECASE)
_FINDING_NOUN_RE = re.compile(rf"\b(?:{_FINDING_NOUN})\b", re.IGNORECASE)
_PENDING_RE = re.compile(r"\[PENDING:[^\]]*\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _extract_section(text: str, name: str) -> str | None:
    """Return the body of the `# <name>` section (any heading level).

    The section runs from just after its heading to the next heading of
    the same or higher level. Case-insensitive on the heading title.
    Returns None when the section is absent.
    """
    lines = text.splitlines()
    start_idx: int | None = None
    start_level = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m is None:
            continue
        level, title = len(m.group(1)), m.group(2).strip().lower()
        if start_idx is None and title == name.lower():
            start_idx = i + 1
            start_level = level
            continue
        if start_idx is not None and level <= start_level:
            return "\n".join(lines[start_idx:i])
    if start_idx is not None:
        return "\n".join(lines[start_idx:])
    return None


def _is_finding_claim(sentence: str) -> bool:
    """True when a sentence asserts a magnitude/direction empirical finding."""
    return bool(_MAGNITUDE_RE.search(sentence) and _FINDING_NOUN_RE.search(sentence))


def scan_discussion_results(text: str) -> list[ConsistencyFinding]:
    """Flag Discussion sentences that interpret findings absent from Results.

    Returns one finding per offending Discussion sentence. Empty list when
    Results is populated, when either section is missing, or when the
    Discussion makes no magnitude/direction claims.
    """
    results_body = _extract_section(text, "Results")
    discussion_body = _extract_section(text, "Discussion")
    if not results_body or not discussion_body:
        return []

    # Guard: only a placeholder-laden Results section creates the contradiction.
    if not _PENDING_RE.search(results_body):
        return []

    # Map each Discussion line to its absolute line number in the document.
    discussion_start = text.splitlines().index(discussion_body.splitlines()[0]) + 1 if discussion_body.strip() else 0

    findings: list[ConsistencyFinding] = []
    for offset, line in enumerate(discussion_body.splitlines()):
        if not line.strip():
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            sentence = sentence.strip()
            if sentence and _is_finding_claim(sentence):
                findings.append(
                    ConsistencyFinding(
                        claim_text=sentence,
                        line=discussion_start + offset,
                        severity="BLOCKING",
                    )
                )
    return findings


def format_consistency_report(findings: list[ConsistencyFinding]) -> str:
    """Format findings as a markdown section for the integrity report artifact."""
    if not findings:
        return (
            "## Discussion-Results Consistency\n\n"
            "No fabricated-interpretation findings: the Discussion makes no "
            "magnitude/direction claims about unpopulated Results.\n"
        )
    lines = [
        "## Discussion-Results Consistency\n",
        "Discussion asserts findings the Results section does not contain "
        "(Results still has `[PENDING:]` values):\n",
        "| Severity | Line | Claimed in Discussion |",
        "|---|---|---|",
    ]
    lines.extend(f"| {f.severity} | {f.line} | {f.claim_text} |" for f in findings)
    return "\n".join(lines) + "\n"
