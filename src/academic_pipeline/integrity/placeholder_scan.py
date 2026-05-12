"""Deterministic placeholder/fabrication-marker scanner for integrity checks.

Runs as a pre-flight check inside IntegrityCheckNode, before the LLM-based
verification agent. Catches known patterns regardless of LLM judgment.

Severity levels:
- BLOCKING: must NEVER appear in any paper text (placeholder strings that
  indicate forgotten substitution, e.g. CRD42024-XXXXXX, TBD, [redacted])
- PENDING: acceptable in intermediate drafts but blocked at final integrity
  (e.g. [PENDING: pooled estimate from full meta-analysis])
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class PlaceholderFinding:
    """A single placeholder match found by the scanner."""

    pattern: str
    label: str
    match: str
    line: int
    severity: str  # "BLOCKING" or "PENDING"


# Tuples of (regex, human label, severity).
# IMPORTANT: order matters only for documentation; all patterns are scanned.
_PATTERNS: Final[list[tuple[str, str, str]]] = [
    (r"\bCRD\d+[-_]?X+\b", "PROSPERO placeholder", "BLOCKING"),
    (r"\bNCT0X+\b", "ClinicalTrials.gov placeholder", "BLOCKING"),
    (r"\bOSF[-_]?X+\b", "OSF placeholder", "BLOCKING"),
    # Generic XXXX: must NOT be preceded by alphanumeric/underscore/dash,
    # which would mean it's part of a registry ID (CRD..., NCT0..., OSF-...).
    # Standalone XXXXX in prose is what this catches.
    (
        r"(?<![A-Za-z0-9_-])XXXX+\b",
        "Generic XXXX placeholder",
        "BLOCKING",
    ),
    (r"\bTBD\b", "TBD marker", "BLOCKING"),
    (r"\bTODO\b", "TODO marker", "BLOCKING"),
    (r"\[INSERT [^\]]+\]", "INSERT placeholder", "BLOCKING"),
    (r"\[redacted\]", "Redaction placeholder", "BLOCKING"),
    (r"\[PENDING:[^\]]+\]", "Pending value", "PENDING"),
]


def scan_placeholders(text: str) -> list[PlaceholderFinding]:
    """Scan text for placeholder/fabrication markers.

    Returns one finding per match. Severity distinguishes blocking placeholders
    (must never reach final paper) from PENDING markers (acceptable in
    intermediate drafts but blocked at final integrity).
    """
    findings: list[PlaceholderFinding] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for pattern, label, severity in _PATTERNS:
            findings.extend(
                PlaceholderFinding(
                    pattern=pattern,
                    label=label,
                    match=m.group(0),
                    line=line_no,
                    severity=severity,
                )
                for m in re.finditer(pattern, line)
            )
    return findings


def format_findings_report(findings: list[PlaceholderFinding]) -> str:
    """Format findings as a markdown table for inclusion in integrity report."""
    if not findings:
        return "## Placeholder Scan\n\nNo placeholders or fabrication markers found.\n"

    lines = [
        "## Placeholder Scan\n",
        "| Severity | Label | Match | Line |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {f.severity} | {f.label} | `{f.match}` | {f.line} |" for f in findings
    )
    return "\n".join(lines) + "\n"
