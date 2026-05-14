"""Methodology-aware reporting-guideline selection for the compliance check.

run-0511-2107 close-read, Bug 4: ComplianceCheckNode ran only the
PRISMA-trAIce *AI-use disclosure* checklist. For a survey paper that
checklist's study-design items (search strategy, eligibility criteria,
SLR stages) are all not-applicable, so the compliance check contributed
nothing.

This module detects the paper's study design from its Methods section
and returns the matching reporting guideline's core items:
  - SYSTEMATIC_REVIEW -> PRISMA
  - SURVEY            -> CHERRIES
  - OBSERVATIONAL     -> STROBE
  - EXPERIMENTAL      -> CONSORT
  - UNKNOWN           -> generic minimal-reporting items

ComplianceCheckNode appends these items to the (methodology-agnostic)
AI-use disclosure checklist so every paper is scored against the
reporting standard that actually applies to it.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final


__all__ = [
    "StudyDesign",
    "detect_study_design",
    "design_reporting_items",
    "build_compliance_prompt",
]


class StudyDesign(StrEnum):
    """The study design a paper reports — drives reporting-guideline choice."""

    SYSTEMATIC_REVIEW = "systematic_review"
    EXPERIMENTAL = "experimental"
    SURVEY = "survey"
    OBSERVATIONAL = "observational"
    UNKNOWN = "unknown"


# Detection keyword sets. Checked in priority order: a systematic review *of*
# surveys is still a systematic review; an RCT that collects outcomes via
# questionnaire is still an RCT. Hence SYSTEMATIC_REVIEW > EXPERIMENTAL >
# SURVEY > OBSERVATIONAL.
_DESIGN_PATTERNS: Final[list[tuple[StudyDesign, re.Pattern[str]]]] = [
    (
        StudyDesign.SYSTEMATIC_REVIEW,
        re.compile(
            r"\bsystematic review\b|\bmeta-?analys[ie]s\b|\bPRISMA\b"
            r"|\bsearch strateg(?:y|ies)\b",
            re.IGNORECASE,
        ),
    ),
    (
        StudyDesign.EXPERIMENTAL,
        re.compile(
            r"\brandomi[sz]ed\b|\brandomi[sz]ed controlled trial\b|\bRCT\b"
            r"|\bcontrol(?:led)? (?:group|trial|arm)\b|\btreatment group\b"
            r"|\ballocation concealment\b",
            re.IGNORECASE,
        ),
    ),
    (
        StudyDesign.SURVEY,
        re.compile(
            r"\bsurvey\b|\bquestionnaire\b|\bLikert\b|\brespondents?\b"
            r"|\bself-report(?:ed)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        StudyDesign.OBSERVATIONAL,
        re.compile(
            r"\bcohort\b|\bcase-control\b|\bobservational\b|\bcross-sectional\b"
            r"|\blongitudinal study\b",
            re.IGNORECASE,
        ),
    ),
]

_METHODS_HEADING_RE = re.compile(
    r"^#{1,6}\s+(materials?\s+and\s+)?method(s|ology)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def _methods_region(text: str) -> str:
    """Return the Methods/Methodology section body, or the whole text if absent.

    Study-design signal lives in the Methods section; scanning there avoids
    false positives from, e.g., a Related Work paragraph that merely mentions
    "survey". Falls back to the whole document when no Methods heading exists.
    """
    m = _METHODS_HEADING_RE.search(text)
    if m is None:
        return text
    start = m.end()
    nxt = _ANY_HEADING_RE.search(text, start)
    return text[start : nxt.start()] if nxt else text[start:]


def detect_study_design(text: str) -> StudyDesign:
    """Detect a paper's study design from its Methods section.

    Returns UNKNOWN when no design keyword matches. Priority order resolves
    papers that mention multiple designs (see _DESIGN_PATTERNS).
    """
    region = _methods_region(text)
    for design, pattern in _DESIGN_PATTERNS:
        if pattern.search(region):
            return design
    return StudyDesign.UNKNOWN


_REPORTING_ITEMS: Final[dict[StudyDesign, str]] = {
    StudyDesign.SYSTEMATIC_REVIEW: """\
PRISMA core reporting items (systematic review / meta-analysis):
- Eligibility criteria stated (inclusion/exclusion)
- Information sources and full search strategy reported
- Study-selection process and PRISMA flow counts (identified -> included)
- Risk-of-bias assessment method described
- Synthesis methods (narrative vs meta-analytic) specified""",
    StudyDesign.SURVEY: """\
CHERRIES core reporting items (Checklist for Reporting Results of Internet
E-Surveys):
- Survey instrument design and item source/adaptation described
- Sampling frame and recruitment channels stated
- Response rate (or completion rate) reported with denominator
- Informed consent and voluntariness documented
- Instrument validation (pilot, reliability, factor structure) reported""",
    StudyDesign.OBSERVATIONAL: """\
STROBE core reporting items (observational studies):
- Study design named explicitly in the methods (cohort / case-control /
  cross-sectional)
- Setting, locations, and relevant dates given
- Eligibility criteria and sources/methods of participant selection
- Variables defined (outcomes, exposures, predictors, confounders)
- Statistical methods, including handling of confounding and missing data""",
    StudyDesign.EXPERIMENTAL: """\
CONSORT core reporting items (randomized controlled trials):
- Randomization: sequence generation method described
- Allocation concealment mechanism described
- Blinding (who was blinded) reported, or its absence justified
- Sample-size determination / power analysis reported
- Participant flow (enrolled -> allocated -> analyzed) reported""",
    StudyDesign.UNKNOWN: """\
Generic minimal-reporting items (study design could not be auto-detected):
- Study design clearly stated in the methods
- Sampling / participant-selection or data-source procedure described
- Analysis plan reported before results
- Limitations of the design discussed""",
}


def design_reporting_items(design: StudyDesign) -> str:
    """Return the core reporting-guideline checklist text for a study design."""
    return _REPORTING_ITEMS[design]


# Cap on paper text injected into the compliance prompt — matches the
# 50k-char cap IntegrityCheckNode applies to the integrity_verification prompt.
_PAPER_TEXT_CAP: Final[int] = 50_000


def build_compliance_prompt(
    ai_disclosure_checklist: str,
    draft_markdown: str,
    compliance_stage: str,
) -> str:
    """Compose the compliance-check prompt for a paper.

    The compliance check has two axes:
      1. AI-use disclosure (methodology-agnostic) — the caller-supplied
         ``ai_disclosure_checklist`` (PRISMA-trAIce items), applies to every
         AI-assisted paper.
      2. Study-design reporting — routed by ``detect_study_design`` so a
         survey is scored against CHERRIES, an RCT against CONSORT, etc.,
         instead of every study-design item coming back not-applicable.
    """
    design = detect_study_design(draft_markdown)
    design_items = design_reporting_items(design)
    return (
        f"Stage: {compliance_stage}\n\n"
        f"Detected study design: {design.value}\n\n"
        f"=== PART 1 — AI-Use Disclosure ===\n{ai_disclosure_checklist}\n\n"
        f"=== PART 2 — Study-Design Reporting ===\n{design_items}\n\n"
        f"Score every item in BOTH parts. An item is NOT_APPLICABLE only when "
        f"it genuinely cannot apply to this study design — do not mark an item "
        f"NOT_APPLICABLE merely because the paper omitted it.\n\n"
        f"Paper:\n{draft_markdown[:_PAPER_TEXT_CAP]}"
    )
