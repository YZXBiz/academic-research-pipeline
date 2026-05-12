"""Output validator for the structured ethics checklist agent.

Attached to the ``ethics_review`` agent as an :func:`output_validator`. On any
violation of the checklist's invariants the validator raises
:class:`pydantic_ai.ModelRetry`, and PydanticAI auto-retries the LLM call.

Invariants enforced:

1. ``items`` length equals ``len(STANDARD_ITEMS)`` and items appear in the
   canonical order.
2. Every justification is at least 20 chars (also enforced by the model, but
   re-checked here for defense in depth).
3. Every item with ``answer=False`` and ``waiver=None`` appears in
   ``blocker_items``.
4. Every item with ``answer=False`` and ``waiver`` set does NOT appear in
   ``blocker_items``.
5. ``overall_verdict`` matches the implied state:

   - ``block`` when any blocker is present
   - ``pass_with_waivers`` when there are waived non-compliances but no blockers
   - ``pass`` when all items are compliant
"""

from __future__ import annotations

from pydantic_ai import ModelRetry

from academic_pipeline.models.ethics import STANDARD_ITEMS, EthicsChecklist


def validate_ethics_checklist(output: EthicsChecklist) -> EthicsChecklist:
    """Validate the structured ethics checklist or raise :class:`ModelRetry`.

    Returns ``output`` unchanged on success; raises :class:`ModelRetry` with a
    diagnostic message on the first violation found, in roughly the order
    listed in the module docstring.
    """
    # 1. Exactly the standard items, in canonical order
    actual_names = [item.name for item in output.items]
    expected_names = list(STANDARD_ITEMS)
    if actual_names != expected_names:
        raise ModelRetry(
            "Checklist items must be exactly these, in this order: "
            f"{expected_names}. Got: {actual_names}."
        )

    for item in output.items:
        # 2. Justification min length
        if len(item.justification) < 20:
            raise ModelRetry(
                f"Item '{item.name}' has insufficient justification "
                "(must be at least 20 characters)."
            )
        # 3. False without waiver -> must be in blocker_items
        if (
            item.answer is False
            and item.waiver is None
            and item.name not in output.blocker_items
        ):
            raise ModelRetry(
                f"Item '{item.name}' is non-compliant without a waiver but is "
                "missing from blocker_items."
            )
        # 4. False WITH waiver -> must NOT be in blocker_items
        if (
            item.answer is False
            and item.waiver is not None
            and item.name in output.blocker_items
        ):
            raise ModelRetry(
                f"Item '{item.name}' has a waiver but is incorrectly listed "
                "in blocker_items."
            )

    # 5. overall_verdict must match implied state
    has_block = bool(output.blocker_items)
    has_waiver = any(
        item.answer is False and item.waiver is not None for item in output.items
    )
    expected_verdict = (
        "block" if has_block else ("pass_with_waivers" if has_waiver else "pass")
    )
    if output.overall_verdict != expected_verdict:
        raise ModelRetry(
            f"overall_verdict={output.overall_verdict!r} contradicts the items: "
            f"expected {expected_verdict!r} based on blocker_items and waivers."
        )

    return output
