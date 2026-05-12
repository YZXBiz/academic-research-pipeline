"""Output validator for the synthesis agent (PRD §6.1.T3).

Attached to the ``synthesis`` agent as an :func:`output_validator` via the
``Agent.output_validator`` decorator. PydanticAI auto-retries the LLM call up
to ``output_retries`` (configured in ``synthesis.yaml``) on
:class:`pydantic_ai.ModelRetry`.

This validator enforces SynthesisReport invariants beyond what Pydantic
already validates at the schema level. The thesis-presence check is
node-level (in :class:`SynthesisNode.run` via ``validate_state``) because
output_validators see only the agent output and per-call deps — not the
graph-level :class:`ResearchState`. Defense in depth: this validator catches
empty-content drift in the SynthesisReport itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import ModelRetry


if TYPE_CHECKING:
    from academic_pipeline.models.research import SynthesisReport


def validate_synthesis_report(output: SynthesisReport) -> SynthesisReport:
    """Validate the SynthesisReport content or raise :class:`ModelRetry`.

    PRD §6.1.T3: enforce that the synthesis is substantive, not a degenerate
    placeholder. Pydantic already constrains ``themes`` to 3-7 entries; this
    validator additionally ensures each list field is non-empty so the writer
    downstream has real material to quote and the trace tokens have something
    to anchor on.

    Returns the output unchanged on success; raises :class:`ModelRetry` with a
    diagnostic message on the first violation found.
    """
    if not output.themes:
        raise ModelRetry(
            "SynthesisReport.themes is empty. Provide 3-7 themes synthesizing "
            "the bibliography findings, anchored on the development chain's "
            "terminal unsolved problem (the thesis)."
        )
    if not output.research_gaps:
        raise ModelRetry(
            "SynthesisReport.research_gaps is empty. Identify at least one " "research gap that the thesis addresses."
        )
    if not output.key_debates:
        raise ModelRetry(
            "SynthesisReport.key_debates is empty. Surface at least one "
            "key debate from the bibliography that the synthesis must adjudicate."
        )
    if not output.methodology_recommendations:
        raise ModelRetry(
            "SynthesisReport.methodology_recommendations is empty. Provide at "
            "least one methodological recommendation flowing from the synthesis."
        )
    return output
