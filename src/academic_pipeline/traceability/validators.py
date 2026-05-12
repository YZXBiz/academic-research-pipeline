"""Output validator factory for the writer-numerical gate.

Attached to section_writer agents via agent.run(output_validators=[validate]).
PydanticAI auto-retries on ModelRetry; UnexpectedModelBehavior aborts (no retry).

Regex `_get_numeric_value_pattern` is ported verbatim from data-to-paper:
  src/data_to_paper/code_and_output_files/ref_numeric_values.py::get_numeric_value_pattern
(MIT-licensed)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior

from academic_pipeline.traceability._patterns import NUM_TOKEN_PATTERN


if TYPE_CHECKING:
    from collections.abc import Callable

    from academic_pipeline.models.numerical import NumericalStore


class _HasText(Protocol):
    text: str
    section_name: str


# === Configurable knobs ===
HEDGE_PROXIMITY_TOKENS: int = 5
"""Number of word tokens before a ⟨num:...⟩ token where a hedge phrase triggers retry."""

FORBIDDEN_PHRASES: tuple[str, ...] = (
    "approximately", "around", "roughly", "circa", "~",
)
"""Hedge words. Trigger ModelRetry if within HEDGE_PROXIMITY_TOKENS of a number."""

ABORTING_PHRASES: tuple[str, ...] = (
    "[insert", "[unknown", "[to be determined", "[to be", "subject to revision",
    "pending full search", "<insert", "<unknown", "<missing",
)
"""Phrases that signal placeholder writing. Trigger UnexpectedModelBehavior (no retry)."""


# === Regex (ported from data-to-paper verbatim) ===
def _get_numeric_value_pattern(must_follow: str | None = None, allow_commas: bool = True) -> str:
    """Get a pattern for a numeric value optionally constrained by a preceding context."""
    must_follow = "" if must_follow is None else rf"(?<={must_follow})"
    if allow_commas:
        pattern = r"(?:[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?|\d{1,3}(?:,\d{3})+)(?!\d)"
    else:
        pattern = r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
    return must_follow + pattern


_NUMERIC_PATTERN = _get_numeric_value_pattern(must_follow=r"[$,{<=\s\n\(\[]", allow_commas=True)


def _strip_num_tokens(text: str) -> str:
    """Remove ⟨num:label⟩ tokens so subsequent regex doesn't see numbers inside them."""
    return re.sub(NUM_TOKEN_PATTERN, "[NUM]", text)


def make_numeric_output_validator(
    store: NumericalStore,
    forbidden_phrases: tuple[str, ...] = FORBIDDEN_PHRASES,
    aborting_phrases: tuple[str, ...] = ABORTING_PHRASES,
) -> Callable[[_HasText], _HasText]:
    """Build an output validator bound to the given numerical store.

    The returned function is intended for use with agent.run(output_validators=[fn]).
    """

    def validate(output: _HasText) -> _HasText:
        text = output.text
        section_name = getattr(output, "section_name", "unknown")

        # 1. Aborting phrases — no retry
        for phrase in aborting_phrases:
            if phrase.lower() in text.lower():
                raise UnexpectedModelBehavior(
                    f"Aborting phrase '{phrase}' detected in section '{section_name}'. "
                    f"The writer must produce a complete grounded section, not a placeholder. "
                    f"This may indicate upstream synthesis is too thin to write from."
                )

        # 2. Unknown ⟨num:label⟩ tokens
        for match in re.finditer(NUM_TOKEN_PATTERN, text):
            label = match.group("label")
            if label not in store.products:
                available_sample = list(store.products.keys())[:10]
                raise ModelRetry(
                    f"Label '{label}' is not in the numerical store. "
                    f"Available labels (showing up to 10): {available_sample}. "
                    f"Use ⟨num:label⟩ only with these labels, or write [GAP] if you don't have the value."
                )

        # 3. Raw numbers in prose without ⟨num:...⟩ wrapping
        stripped = _strip_num_tokens(text)
        bare = re.findall(_NUMERIC_PATTERN, stripped)
        if bare:
            raise ModelRetry(
                f"The number '{bare[0]}' appears in prose without a ⟨num:...⟩ wrapper. "
                f"Either reference an existing label from the store or write [GAP]. "
                f"All numerical claims in the manuscript must be traceable."
            )

        # 4. Hedge phrases near ⟨num:...⟩ tokens
        for match in re.finditer(NUM_TOKEN_PATTERN, text):
            preceding = text[: match.start()].split()
            window = preceding[-HEDGE_PROXIMITY_TOKENS:]
            for phrase in forbidden_phrases:
                if any(phrase.lower() in tok.lower() for tok in window):
                    raise ModelRetry(
                        f"Hedge phrase '{phrase}' appears within {HEDGE_PROXIMITY_TOKENS} "
                        f"tokens before ⟨num:{match.group('label')}⟩. "
                        f"Either remove the hedge or remove the precise number."
                    )

        return output

    return validate
