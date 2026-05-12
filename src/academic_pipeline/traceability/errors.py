"""Typed exceptions for the traceability layer.

Every traceability failure inherits from TraceabilityError and carries a stable
error_code (TRC001-TRC006) for postmortem grep over events.jsonl.

Exception class names below intentionally omit the "Error" suffix because the
codes themselves (TRC001-TRC006) are the canonical identifiers and the names
match the SCI Traceability spec; N818 is silenced per-class.
"""

from __future__ import annotations


class TraceabilityError(Exception):
    """Base for all traceability failures. Never raise directly."""

    error_code: str = "TRC000"


class NumericValidatorRetry(TraceabilityError):  # noqa: N818
    """Writer output failed the numeric gate. PydanticAI auto-retries via ModelRetry."""

    error_code = "TRC001"

    def __init__(
        self,
        message: str,
        *,
        section_name: str | None = None,
        violation_type: str | None = None,
        offending_token: str | None = None,
    ) -> None:
        """Store retry-context fields alongside the human-readable message."""
        super().__init__(message)
        self.section_name = section_name
        self.violation_type = violation_type
        self.offending_token = offending_token


class NumericValidatorAbort(TraceabilityError):  # noqa: N818
    """Aborting phrase detected. Writer is fundamentally confused. No retry."""

    error_code = "TRC002"

    def __init__(
        self,
        message: str,
        *,
        section_name: str | None = None,
        aborting_phrase: str | None = None,
        position: int | None = None,
    ) -> None:
        """Store the aborting phrase and its position alongside the message."""
        super().__init__(message)
        self.section_name = section_name
        self.aborting_phrase = aborting_phrase
        self.position = position


class SubstitutionFailure(TraceabilityError):  # noqa: N818
    """Renderer found a ⟨num:label⟩ that doesn't resolve in the store. Bug, not LLM error."""

    error_code = "TRC003"

    def __init__(
        self,
        message: str,
        *,
        label: str | None = None,
        section_name: str | None = None,
        store_label_count: int = 0,
    ) -> None:
        """Store the missing label and store size for postmortem grep."""
        super().__init__(message)
        self.label = label
        self.section_name = section_name
        self.store_label_count = store_label_count


class StoreIntegrityError(TraceabilityError):
    """NumericalStore violates an invariant (duplicate label, missing source_code_line)."""

    error_code = "TRC004"

    def __init__(
        self,
        message: str,
        *,
        invariant_name: str | None = None,
        offending_label: str | None = None,
    ) -> None:
        """Store the violated invariant name and offending label."""
        super().__init__(message)
        self.invariant_name = invariant_name
        self.offending_label = offending_label


class CopilotTimeout(TraceabilityError):  # noqa: N818
    """Copilot stdin read exceeded timeout. Continues autonomous; not a real failure."""

    error_code = "TRC005"

    def __init__(self, message: str, *, checkpoint_name: str | None = None, timeout_s: int = 60) -> None:
        """Store the checkpoint name and timeout duration in seconds."""
        super().__init__(message)
        self.checkpoint_name = checkpoint_name
        self.timeout_s = timeout_s


class DialogueExhaustion(TraceabilityError):  # noqa: N818
    """Writer↔reviewer dialogue hit max_turns without termination phrase."""

    error_code = "TRC006"

    def __init__(
        self,
        message: str,
        *,
        section_name: str | None = None,
        turn_count: int = 0,
        last_review_excerpt: str | None = None,
    ) -> None:
        """Store the turn count and last review excerpt for postmortem inspection."""
        super().__init__(message)
        self.section_name = section_name
        self.turn_count = turn_count
        self.last_review_excerpt = last_review_excerpt


# Fields that are common Exception/object internals and must not leak into
# the events.jsonl record. Anything else on the instance dict is treated as
# event-relevant context (PRD §6.10.T6).
_EVENT_HIDDEN_FIELDS: frozenset[str] = frozenset({"args", "with_traceback"})


def traceability_error_event(error: TraceabilityError) -> dict[str, object]:
    """Return an events.jsonl payload for a TraceabilityError (PRD §6.10.T6).

    The shape is `{"error_code": "TRC###", "message": "...", **context}` where
    context is every public instance attribute the exception declared. The
    caller is responsible for adding `ts`/`type` via `EventLogger.emit_sync`
    or `emit`.
    """
    payload: dict[str, object] = {
        "error_code": error.error_code,
        "message": str(error),
    }
    for name, value in vars(error).items():
        if name.startswith("_") or name in _EVENT_HIDDEN_FIELDS:
            continue
        payload[name] = value
    return payload
