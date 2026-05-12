"""Shared context builder for agent prompts."""

from __future__ import annotations

import json
from typing import Any

from academic_pipeline.runtime.parsing import check_dialogue_health


def extract_field_text(state: object, field_name: str) -> str:
    """Extract a text representation from a single state field.

    Handles dicts (uses JSON for structured data), lists (joins items), and plain strings. Returns empty string for
    falsy values.
    """
    from pydantic import BaseModel

    value: Any = getattr(state, field_name, None)
    if not value:
        return ""
    if isinstance(value, BaseModel):
        return value.model_dump_json(indent=2)
    if isinstance(value, dict):
        raw = value.get("raw")
        if raw is not None:
            return str(raw)
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def build_context(state: object, keys: list[str], node_name: str | None = None) -> str:
    """Build a context string from state fields for agent prompts.

    Args:
        state: A dataclass state object with named attributes.
        keys: List of field names to include in the context.
        node_name: If provided, checks for revision_context on state and appends revision instructions when the
            target_node matches. Clears revision_context after consumption (single point of responsibility).

    Returns:
        Concatenated context string with field labels and values.
    """
    parts: list[str] = []
    for key in keys:
        text = extract_field_text(state, key)
        if text:
            parts.append(f"{key}:\n{text}")

    # Revision context injection
    if node_name is not None:
        revision_ctx = getattr(state, "revision_context", None)
        if revision_ctx is not None and revision_ctx.target_node == node_name:
            issues_lines = [
                f"- [{issue.severity}] {issue.dimension}: "
                f"{issue.description}. Recommendation: {issue.recommendation}"
                for issue in revision_ctx.issues
            ]
            issues_text = "\n".join(issues_lines) if issues_lines else "- No specific issues listed."

            revision_block = (
                f"REVISION INSTRUCTIONS:\n"
                f"Round: {revision_ctx.round}\n"
                f"Source: {revision_ctx.source}\n"
                f"Weakest dimension: {revision_ctx.weakest_dimension}\n"
                f"Feedback: {revision_ctx.feedback_summary}\n"
                f"Issues to address:\n{issues_text}\n\n"
                f"Your previous output:\n{revision_ctx.previous_output}\n\n"
                f"Revise your output to address these issues. "
                f"Do not regenerate from scratch — improve what you wrote."
            )
            parts.append(revision_block)

            # Clear after consumption (single point of responsibility)
            state.revision_context = None  # type: ignore[attr-defined]

    return "\n\n".join(parts)


def build_curated_context(state: object, spec: object) -> str:
    """Build a curated agent context from a ContextSpec.

    Walks state by spec.allowed_products only and filters the numerical_store to
    spec.allowed_numerical_labels. Used by writer agents that need a specific
    slice of state plus a controlled view of the numerical store.

    Args:
        state: A state object (dataclass or BaseModel) with named attributes.
        spec: A traceability.context_spec.ContextSpec instance.

    Returns:
        Concatenated context string with field labels and (when applicable)
        a table of available numerical values for the writer to cite via
        ⟨num:label⟩ tokens.

    Raises:
        TypeError: if `spec` is not a ContextSpec instance.
    """
    from academic_pipeline.models.numerical import NumericalStore
    from academic_pipeline.traceability.context_spec import ContextSpec

    if not isinstance(spec, ContextSpec):
        raise TypeError(f"build_curated_context requires ContextSpec, got {type(spec)}")

    parts: list[str] = []
    for key in spec.allowed_products:
        text = extract_field_text(state, key)
        if text:
            parts.append(f"{key}:\n{text}")

    # Numerical-store table — only emitted when store is non-empty AND at least one allowed label resolves
    store = getattr(state, "numerical_store", None)
    if isinstance(store, NumericalStore) and store.products:
        if spec.allowed_numerical_labels == "all":
            labels = list(store.products.keys())
        else:
            labels = [lbl for lbl in spec.allowed_numerical_labels if lbl in store.products]
        if labels:
            table_lines = ["", "Available numerical values (cite using ⟨num:label⟩):"]
            for label in labels:
                p = store.products[label]
                unit_str = f" {p.unit}" if p.unit else ""
                table_lines.append(f"- {label} = {p.value}{unit_str} — {p.context}")
            parts.append("\n".join(table_lines))

    return "\n\n".join(parts)


def format_health_prefix(messages: list[dict[str, str]]) -> str:
    """Build a dialogue health warning prefix for agent prompts.

    Calls check_dialogue_health() and formats any warnings into a bracketed prefix string. Returns empty string if no
    warnings.
    """
    health_warnings = check_dialogue_health(messages)
    if not health_warnings:
        return ""
    return (
        "[DIALOGUE HEALTH WARNING: "
        + "; ".join(health_warnings)
        + ". Consider whether genuine consensus has been reached "
        "or if challenges are being suppressed.]\n\n"
    )
