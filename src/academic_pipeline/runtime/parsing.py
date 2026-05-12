"""Parsers for extracting structured values from LLM output."""

from __future__ import annotations

import re


_AGREEMENT_MARKERS = frozenset({
    "i agree",
    "you're right",
    "good point",
    "no issues",
    "that's correct",
    "fair point",
    "well said",
})

_CONFLICT_AVOIDANCE_PATTERNS = [
    re.compile(r"no\s+critical\s+issues", re.IGNORECASE),
    re.compile(r"no\s+major\s+issues", re.IGNORECASE),
    re.compile(r"no\s+minor\s+issues", re.IGNORECASE),
]


def check_dialogue_health(messages: list[dict[str, str]], window: int = 5) -> list[str]:
    """Check recent assistant messages for dialogue health issues.

    Scans the last *window* assistant messages for:

    1. **Persistent Agreement** -- 3+ consecutive messages with agreement markers.
    2. **Conflict Avoidance** -- output that finds zero issues at any severity level.

    Returns:
        List of warning strings. Empty list means healthy dialogue.
    """
    assistant_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]
    recent = assistant_msgs[-window:] if len(assistant_msgs) > window else assistant_msgs

    warnings: list[str] = []

    consecutive_agreements = 0
    for msg in recent:
        lower = msg.lower()
        if any(marker in lower for marker in _AGREEMENT_MARKERS):
            consecutive_agreements += 1
        else:
            consecutive_agreements = 0

    if consecutive_agreements >= 3:
        warnings.append(
            "Persistent agreement detected — 3+ consecutive messages show agreement "
            "without challenge. Verify genuine consensus vs. suppressed dissent."
        )

    for msg in recent:
        if all(p.search(msg) for p in _CONFLICT_AVOIDANCE_PATTERNS):
            warnings.append(
                "Conflict avoidance detected — output reports zero issues at all "
                "severity levels. DA/reviewer should find at least 1 issue per checkpoint."
            )
            break

    return warnings
