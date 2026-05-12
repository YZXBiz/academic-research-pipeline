"""Code-enforced hard-veto rules for agent output evaluation.

A veto function inspects an output string and returns either:
- None: no violation, output may pass
- str: a human-readable description of the violation

When applied via apply_hard_vetos, ANY veto firing forces verdict=NEEDS_IMPROVEMENT
regardless of what the LLM rubric scored. This is the enforcement layer that
catches what prompt instructions and LLM rubrics miss.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from academic_pipeline.models.shared import EvaluationResult


VetoFn = Callable[[str], str | None]


# Patterns that should never appear in finalised section content.
# Note: [PENDING: ...] is the SANCTIONED form for explicit deferrals
# (per section_writer.yaml line 67-75) and is NOT vetoed.
_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:PROSPERO\s+)?CRD\d+[-_]?X{3,}\b"), "PROSPERO/CRD placeholder"),
    (re.compile(r"\bNCT0?X{3,}\b"), "NCT placeholder"),
    (re.compile(r"\bOSF[-_]?X{3,}\b"), "OSF placeholder"),
    (re.compile(r"\[redacted\]", re.IGNORECASE), "[redacted] marker"),
    # [INSERT ...] but NOT [PENDING: ...] (which is sanctioned)
    (re.compile(r"\[INSERT[^\]]*\]", re.IGNORECASE), "[INSERT...] marker"),
    (re.compile(r"\b(?:TODO|TBD|FIXME)\b"), "TODO/TBD/FIXME marker"),
    # Dangling bold from mid-token truncation (e.g. "**Ob" at line end with no closing **)
    (re.compile(r"\*\*[A-Z][a-z]{0,4}\s*$", re.MULTILINE), "dangling bold marker"),
]


def no_placeholder_tokens(text: str) -> str | None:
    """Veto if any agent-leaked placeholder token appears in text."""
    hits: list[str] = []
    for pattern, label in _PLACEHOLDER_PATTERNS:
        hits.extend(f'{label} "{match.group(0).strip()}"' for match in pattern.finditer(text))
    if hits:
        # Cap to first 5 to keep feedback readable
        return "Forbidden placeholder tokens present: " + "; ".join(hits[:5])
    return None


# Bare LaTeX commands outside $...$ math mode.
# We match \word and check if `word` is in the math whitelist.
# The negative lookahead approximates "not followed by a $ on the same line"
# which catches the common case `\rho = 0.5` (no closing $).
_BARE_LATEX_RE = re.compile(r"(?<!\$)(?<!\\)\\([a-zA-Z]+)(?![^\n$]*\$)")

_LATEX_MATH_CMD_NAMES = frozenset(
    {
        # Greek (lower)
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "varepsilon",
        "zeta",
        "eta",
        "theta",
        "vartheta",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
        "xi",
        "pi",
        "varpi",
        "rho",
        "varrho",
        "sigma",
        "varsigma",
        "tau",
        "upsilon",
        "phi",
        "varphi",
        "chi",
        "psi",
        "omega",
        # Greek (upper)
        "Gamma",
        "Delta",
        "Theta",
        "Lambda",
        "Xi",
        "Pi",
        "Sigma",
        "Upsilon",
        "Phi",
        "Psi",
        "Omega",
        # Math operators / symbols
        "infty",
        "partial",
        "nabla",
        "sum",
        "prod",
        "int",
        "oint",
        # Decorations / structures
        "sqrt",
        "frac",
        "hat",
        "bar",
        "tilde",
        "vec",
        "dot",
        "ddot",
        "boldsymbol",
        "mathbb",
        "mathcal",
        "mathrm",
        "mathit",
        "mathbf",
        # Relations
        "leq",
        "geq",
        "neq",
        "equiv",
        "approx",
        "sim",
        "simeq",
        "propto",
        "subset",
        "supset",
        "in",
        "notin",
        # Operators
        "pm",
        "mp",
        "times",
        "div",
        "cdot",
        "ast",
        "star",
    }
)


def no_bare_latex_commands(text: str) -> str | None:
    r"""Veto if a known LaTeX math command appears outside $...$ math mode.

    Text-mode commands (\textbf, \textit, etc.) and unknown commands
    are NOT vetoed — only the math whitelist triggers.
    """
    hits: list[str] = [
        f"\\{cmd}" for match in _BARE_LATEX_RE.finditer(text) if (cmd := match.group(1)) in _LATEX_MATH_CMD_NAMES
    ]
    if hits:
        unique = sorted(set(hits))
        return (
            f"Bare LaTeX math commands outside $...$ mode: {', '.join(unique[:5])}. "
            f"Wrap in $...$ (e.g. $\\rho$) or use Unicode (e.g. ρ)."  # noqa: RUF001 — Greek rho intentional in LaTeX repair guidance
        )
    return None


# ============================================================================
# PRD §6.11.T2 — hedge phrases near trace tokens + aborting phrases anywhere.
# ============================================================================
#
# These two vetos mirror the writer's own validators.py gate so the
# evaluation panel catches what the upstream gate missed (or what landed
# via a different agent path). The phrase lists are intentionally kept
# verbatim with traceability/validators.py:37-45 so a single edit there
# updates both consumers — see the docstring on each constant below for
# the source-of-truth pointer.

# Verbatim from traceability/validators.py:37-39 (FORBIDDEN_PHRASES).
_HEDGE_PHRASES: tuple[str, ...] = (
    "approximately",
    "around",
    "roughly",
    "circa",
    "~",
)

# Verbatim from traceability/validators.py:42-45 (ABORTING_PHRASES).
_ABORTING_PHRASES: tuple[str, ...] = (
    "[insert",
    "[unknown",
    "[to be determined",
    "[to be",
    "subject to revision",
    "pending full search",
    "<insert",
    "<unknown",
    "<missing",
)

# How many word tokens BEFORE a ⟨num:label⟩ a hedge phrase may appear before
# triggering. Mirrors validators.py::HEDGE_PROXIMITY_TOKENS (default 5).
_HEDGE_PROXIMITY_TOKENS: int = 5

# Trace-token regex — direct copy of traceability/_patterns.py NUM_TOKEN_PATTERN.
_TRACE_TOKEN_RE = re.compile(r"⟨num:(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)⟩")


def hedge_near_trace_token(text: str) -> str | None:
    """Veto if a hedge phrase appears within HEDGE_PROXIMITY_TOKENS BEFORE ⟨num:label⟩.

    Direction matters per Spec 1: hedge phrases AFTER a trace token are not
    flagged because the number itself anchors the precision claim. Hedges
    are flagged anywhere in the body if no trace token appears within the
    proximity window.

    Mirrors traceability/validators.py FORBIDDEN_PHRASES + HEDGE_PROXIMITY_TOKENS.
    """
    # Build a tokenized sliding-window index so we can ask "what are the last
    # N word tokens before this character offset?". `re.split(r"\s+")` with the
    # source positions tracks both content + whitespace boundaries.
    tokens_with_pos: list[tuple[int, str]] = [(match.start(), match.group(0)) for match in re.finditer(r"\S+", text)]

    hits: list[str] = []
    for trace_match in _TRACE_TOKEN_RE.finditer(text):
        trace_start = trace_match.start()
        # Index of the trace token in the token list (the trace token itself is
        # one entry — find it).
        trace_idx = next(
            (i for i, (pos, _) in enumerate(tokens_with_pos) if pos == trace_start),
            None,
        )
        if trace_idx is None:
            continue
        # Look at the N tokens immediately preceding the trace token.
        window_start = max(0, trace_idx - _HEDGE_PROXIMITY_TOKENS)
        window = [tok.lower() for _, tok in tokens_with_pos[window_start:trace_idx]]
        hits.extend(
            f"{hedge!r} within {_HEDGE_PROXIMITY_TOKENS} tokens before {trace_match.group(0)}"
            for hedge in _HEDGE_PHRASES
            if any(hedge in tok for tok in window)
        )

    if hits:
        return "Hedge phrase near trace token: " + "; ".join(hits[:5])
    return None


# [PENDING:] is the SANCTIONED deferral marker per AP56 / section_writer.yaml.
# When an aborting phrase is matched, we additionally check that it is not the
# carve-out form so the legitimate deferral path is preserved.
_PENDING_CARVE_OUT_RE = re.compile(r"\[PENDING:[^\]]*\]", re.IGNORECASE)


def aborting_phrase_present(text: str) -> str | None:
    """Veto if any aborting phrase appears (case-insensitive, anywhere in body).

    Aborting phrases signal placeholder writing the model never resolved.
    Per AP56 the [PENDING: ...] form is the sanctioned deferral marker and
    is exempt — `[to be` and `[insert` would otherwise overlap with it
    inside a [PENDING: ...] block, so we strip those before scanning.

    Mirrors traceability/validators.py ABORTING_PHRASES.
    """
    # Strip sanctioned [PENDING: ...] runs before scanning so they don't
    # accidentally match the broader [to be / [insert / etc. phrases.
    cleaned = _PENDING_CARVE_OUT_RE.sub("", text).lower()

    hits = [phrase for phrase in _ABORTING_PHRASES if phrase.lower() in cleaned]

    if hits:
        return "Aborting placeholder phrase(s) present: " + ", ".join(hits[:5])
    return None


# Bare numeric-content pattern: percentages and decimals that should usually
# be wrapped in ⟨num:label⟩. Conservative Phase 1 scope — integers alone are
# excluded (years, counts, references generate too much noise to flag without
# context). Phase 2 / Phase 4 will refine with whitelist for years, citations,
# table column headers, etc. via the rubric-coverage dimension (§6.11.T3).
_BARE_NUMERIC_RE = re.compile(r"\b\d+(?:\.\d+)?%|\b\d+\.\d+\b")


def missing_trace_token(text: str) -> str | None:
    """Veto if numeric content appears without a ⟨num:label⟩ wrapper.

    Phase 1 implementation flags raw decimal values and percentages that
    are not wrapped in a trace token. This is the anti-fabrication signal
    PRD Spec 1 calls for: every prose-stated number should be traceable
    back to its source via the numerical store.

    Trace-token contents are stripped before scanning so a properly tagged
    number does not false-positive.

    Phase 2 (§6.11.T3) will weight this into the rubric-coverage dimension
    so the evaluator panel can score it instead of binary-vetoing.
    """
    cleaned = _TRACE_TOKEN_RE.sub("", text)
    hits = _BARE_NUMERIC_RE.findall(cleaned)
    if hits:
        return "Numeric value(s) without trace token (use ⟨num:label⟩): " + ", ".join(hits[:5])
    return None


def apply_hard_vetos(
    output_text: str,
    eval_result: EvaluationResult,
    vetos: list[VetoFn],
) -> EvaluationResult:
    """Apply hard-veto checks; force NEEDS_IMPROVEMENT if any veto fires.

    Veto reasons are appended to feedback so the agent gets concrete repair
    guidance on the next revision pass. Scores from the LLM rubric are
    preserved unchanged (informational); only verdict/feedback/weakest are
    overridden.
    """
    reasons = [msg for veto in vetos if (msg := veto(output_text)) is not None]
    if not reasons:
        return eval_result

    combined = " | ".join(reasons)
    new_feedback = (
        eval_result.feedback + " | HARD VETO: " + combined if eval_result.feedback else "HARD VETO: " + combined
    )
    return EvaluationResult(
        verdict="NEEDS_IMPROVEMENT",
        scores=eval_result.scores,
        feedback=new_feedback.strip(" |"),
        weakest_dimension="hard_veto",
    )
