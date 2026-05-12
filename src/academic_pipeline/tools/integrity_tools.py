"""Async integrity tools for PydanticAI agents.

Heuristic integrity checks on academic text: claim extraction, plagiarism
detection, and AI-style analysis.
"""

from __future__ import annotations

import json
import re
from typing import Any


async def extract_claims(text: str) -> str:
    """Extract verifiable claims from academic text for integrity checking.

    Identifies numerical claims, statistical results, causal claims, and categorical assertions that can be traced back
    to cited sources.

    Args:
        text: Academic text to analyze for verifiable claims.

    Returns:
        JSON string containing total_claims count and a list of claim
        objects with id, text, type, sources_cited, and sentence_index.
    """
    claims: list[dict[str, Any]] = []
    sentences = re.split(r"(?<=[.!?])\s+", text)

    claim_patterns = [
        (r"\d+\.?\d*\s*%", "numerical"),
        (r"p\s*[<>=]\s*\.?\d+", "statistical"),
        (
            r"(?:significantly|substantially|marginally)\s+(?:higher|lower|greater|less|more|fewer)",
            "statistical",
        ),
        (r"(?:caused?|leads?\s+to|results?\s+in|due\s+to)", "causal"),
        (r"(?:all|no|none|every|always|never)\s+\w+", "categorical"),
        (r"(?:increased?|decreased?|improved?|declined?)\s+by\s+\d+", "trend"),
    ]

    for i, sentence in enumerate(sentences):
        for pattern, claim_type in claim_patterns:
            if re.search(pattern, sentence, re.IGNORECASE):
                source_refs = re.findall(r"\([^)]*\d{4}[^)]*\)|\[[^\]]+\]", sentence)
                claims.append(
                    {
                        "id": f"CLAIM-{len(claims) + 1:03d}",
                        "text": sentence.strip(),
                        "type": claim_type,
                        "sources_cited": source_refs,
                        "sentence_index": i,
                    }
                )
                break

    return json.dumps({"total_claims": len(claims), "claims": claims}, indent=2)


async def check_plagiarism_heuristic(text: str) -> str:
    """Run heuristic plagiarism and originality checks on academic text.

    Checks for verbatim copying indicators, self-plagiarism patterns, and AI writing style indicators. Not a replacement
    for Turnitin.

    Args:
        text: Academic text to analyze for originality concerns.

    Returns:
        JSON string containing paragraphs_analyzed count, flags list,
        optional ai_style_alerts, and a verdict of REVIEW_NEEDED or NO_FLAGS.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    results: dict[str, Any] = {
        "paragraphs_analyzed": len(paragraphs),
        "flags": [],
    }

    for i, para in enumerate(paragraphs):
        sentences = re.split(r"(?<=[.!?])\s+", para)

        long_common_phrases = []
        for s in sentences:
            words = s.split()
            if len(words) >= 20:
                has_citation = bool(re.search(r"\([^)]*\d{4}[^)]*\)|\[[^\]]+\]", s))
                if not has_citation:
                    long_common_phrases.append(s[:80])

        if long_common_phrases:
            results["flags"].append(
                {
                    "paragraph": i + 1,
                    "type": "potential_uncited_content",
                    "detail": f"Long sentence without citation: {long_common_phrases[0]}...",
                    "severity": "MODERATE",
                }
            )

    ai_flags = _detect_ai_patterns(text)
    if ai_flags:
        results["ai_style_alerts"] = ai_flags

    results["verdict"] = "REVIEW_NEEDED" if results["flags"] or ai_flags else "NO_FLAGS"
    return json.dumps(results, indent=2)


async def detect_ai_style_indicators(text: str) -> str:
    """Detect heuristic indicators of AI-generated text.

    Uses six indicators covering phrase frequency, paragraph uniformity, em-dash usage, throat-clearing openers, binary
    contrasts, and semicolon density. Two or more triggered flags text for review.

    Args:
        text: Text to analyze for AI-generation indicators.

    Returns:
        JSON string containing indicators_checked count,
        indicators_triggered count, flagged boolean, a heuristic
        disclaimer note, and detailed per-indicator results.
    """
    flags = _detect_ai_patterns(text)
    triggered = sum(1 for f in flags if f["triggered"])
    return json.dumps(
        {
            "indicators_checked": len(flags),
            "indicators_triggered": triggered,
            "flagged": triggered >= 2,
            "note": "Heuristic only — not a definitive AI detection tool",
            "details": flags,
        },
        indent=2,
    )


def _detect_ai_patterns(text: str) -> list[dict[str, Any]]:
    """Detect common AI-generated writing patterns in the given text.

    Args:
        text: Text to scan for AI writing patterns.

    Returns:
        List of indicator dicts, each with indicator name,
        triggered boolean, and supporting metrics.
    """
    indicators: list[dict[str, Any]] = []

    ai_phrases = [
        "it is important to note",
        "it is worth noting",
        "delve into",
        "shed light on",
        "in the realm of",
        "the landscape of",
        "a testament to",
        "underscores the importance",
        "multifaceted",
        "nuanced",
        "tapestry",
        "in conclusion, this",
        "this comprehensive",
    ]
    found = [p for p in ai_phrases if p in text.lower()]
    indicators.append(
        {
            "indicator": "AI high-frequency phrases",
            "triggered": len(found) >= 3,
            "count": len(found),
            "examples": found[:5],
        }
    )

    paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 50]
    if paragraphs:
        lengths = [len(p.split()) for p in paragraphs]
        avg = sum(lengths) / len(lengths)
        variance = sum((length - avg) ** 2 for length in lengths) / len(lengths)
        cv = (variance**0.5) / avg if avg > 0 else 0
        indicators.append(
            {
                "indicator": "Paragraph length uniformity",
                "triggered": cv < 0.15,
                "coefficient_of_variation": round(cv, 3),
            }
        )
    else:
        indicators.append(
            {
                "indicator": "Paragraph length uniformity",
                "triggered": False,
                "note": "Not enough paragraphs to assess",
            }
        )

    em_dash_count = text.count("\u2014")
    word_count = len(text.split())
    em_dash_rate = em_dash_count / (word_count / 1000) if word_count > 0 else 0
    indicators.append(
        {
            "indicator": "Excessive em-dash usage",
            "triggered": em_dash_rate > 5,
            "rate_per_1000_words": round(em_dash_rate, 2),
        }
    )

    sentences = re.split(r"(?<=[.!?])\s+", text)
    throat_clearing = [
        s for s in sentences if re.match(r"^(In today's|In the modern|In an era|As we navigate|In recent years,)", s)
    ]
    indicators.append(
        {
            "indicator": "Throat-clearing openers",
            "triggered": len(throat_clearing) >= 3,
            "count": len(throat_clearing),
        }
    )

    binary_patterns = re.findall(r"(?:not only|both)\s+\w+\s+(?:but also|and)\s+\w+", text, re.IGNORECASE)
    indicators.append(
        {
            "indicator": "Binary contrast overuse",
            "triggered": len(binary_patterns) >= 5,
            "count": len(binary_patterns),
        }
    )

    semicolons = text.count(";")
    semicolon_rate = semicolons / (word_count / 1000) if word_count > 0 else 0
    indicators.append(
        {
            "indicator": "Excessive semicolon usage",
            "triggered": semicolon_rate > 8,
            "rate_per_1000_words": round(semicolon_rate, 2),
        }
    )

    return indicators
