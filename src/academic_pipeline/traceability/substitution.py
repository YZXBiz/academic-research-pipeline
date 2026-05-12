r"""Renderer — substitute ⟨num:label⟩ tokens with values.

Runs after writing, before pandoc. For LaTeX output, emits \hyperlink targeting
the label that the Notes appendix declares as a \hypertarget. For HTML, emits
plain values.

Failure is loud: any unresolved token raises SubstitutionFailure (TRC003).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from academic_pipeline.traceability._patterns import NUM_TOKEN_PATTERN
from academic_pipeline.traceability.errors import SubstitutionFailure


if TYPE_CHECKING:
    from academic_pipeline.models.numerical import NumericalStore


_NUM_TOKEN_PATTERN = re.compile(NUM_TOKEN_PATTERN)


def substitute_tokens(
    text: str,
    store: NumericalStore,
    output_format: Literal["latex", "html"] = "latex",
    section_name: str | None = None,
) -> str:
    """Replace every ⟨num:label⟩ token. Raises SubstitutionFailure on unresolved label."""

    def _replace(match: re.Match[str]) -> str:
        label = match.group("label")
        if label not in store.products:
            raise SubstitutionFailure(
                f"⟨num:{label}⟩ does not resolve in store",
                label=label,
                section_name=section_name,
                store_label_count=len(store.products),
            )
        value = store.products[label].value
        if output_format == "latex":
            return rf"\hyperlink{{num_{label}}}{{{value}}}"
        return value

    return _NUM_TOKEN_PATTERN.sub(_replace, text)


def find_unresolved_tokens(text: str, store: NumericalStore) -> list[str]:
    """Return labels of ⟨num:label⟩ tokens in `text` that don't resolve in `store`.

    Non-raising preflight for `substitute_tokens`. Returns labels in
    first-occurrence order with duplicates collapsed. Used by callers that
    want to enumerate ALL unresolved labels before deciding what to do.
    """
    seen: set[str] = set()
    unresolved: list[str] = []
    for match in _NUM_TOKEN_PATTERN.finditer(text):
        label = match.group("label")
        if label in store.products or label in seen:
            continue
        seen.add(label)
        unresolved.append(label)
    return unresolved


def validate_tokens(
    text: str,
    store: NumericalStore,
    section_name: str | None = None,
) -> None:
    """Dry-run check: raise SubstitutionFailure (TRC003) on first unresolved token.

    Performs no substitution and returns None — callers use this when they
    want to fail-fast at gate time rather than wait for the LaTeX renderer
    to blow up. The first unresolved label in document order is reported
    (re.finditer scans left-to-right). Pairs with `find_unresolved_tokens`
    when the caller needs the full list rather than fail-fast. PRD §6.10.T4.
    """
    for match in _NUM_TOKEN_PATTERN.finditer(text):
        label = match.group("label")
        if label not in store.products:
            raise SubstitutionFailure(
                f"⟨num:{label}⟩ does not resolve in store",
                label=label,
                section_name=section_name,
                store_label_count=len(store.products),
            )
