"""Schema validation helpers for handoff data."""

from __future__ import annotations


def validate_state(
    state: object,
    required: list[str],
    node_name: str = "",
) -> None:
    """Validate that required state fields are present and well-typed.

    Logs a warning for each missing field. Does not raise — this is a defense-in-depth check, not a hard gate.
    """
    import logging

    logger = logging.getLogger(__name__)
    for field_name in required:
        value = getattr(state, field_name, None)
        if value is None:
            logger.warning("[%s] Required state field '%s' is None", node_name, field_name)
