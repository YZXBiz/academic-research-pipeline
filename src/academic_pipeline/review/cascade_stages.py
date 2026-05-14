"""Pure stage functions for the cascaded reviewer pipeline (SCI Spec 6 Phase 1).

Each stage is a coroutine that reads from the ReviewState (and PipelineDeps)
and returns a StageResult. The functions are intentionally pure with
respect to graph routing — orchestration (short-circuit logic, padding) is
handled in CascadedReviewNode + cascade_aggregation.

Stage A — Numerical grounding (Spec 1 numerical store + auditor agent)
Stage B — Novelty (Spec 4 PointWiseNoveltyReviewerNode output)
Stage C — Methodology (Spec 5 persona reviewers' findings)
Stage D — Narrative quality (terminal; never short-circuits in Phase 1)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from academic_pipeline.core.enums import PHASE_DIRS, Stage
from academic_pipeline.models.cascade import (
    CascadeStageName,
    StageResult,
    StageVerdict,
)


if TYPE_CHECKING:
    from pydantic_graph import GraphRunContext

    from academic_pipeline.core.deps import PipelineDeps
    from academic_pipeline.review.state import ReviewState


logger = logging.getLogger(__name__)


# Bare-number detection used by Stage A's regex fallback. Matches integers,
# decimals, and percentages NOT already wrapped in a ⟨num:label⟩ token.
# This is a coarse signal — best-effort only when Spec 1 is off.
_BARE_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_TRACE_TOKEN_PATTERN = re.compile(r"⟨num:[^⟩]+⟩")


# ---------------------------------------------------------------------------
# Stage A — Numerical grounding
# ---------------------------------------------------------------------------


async def run_numerical_grounding_stage(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
    manuscript: str,
) -> StageResult:
    """Stage A: verify numerical claims are grounded in the trace store.

    When Spec 1 traceability is enabled (`config.traceability_mode != "off"`)
    AND the numerical_claims_auditor agent is registered, run the auditor
    against the trace store on `pipeline_state.numerical_store`. If it returns
    any ``severity=critical`` finding (and the configured short-circuit flag
    is on), → SHORT_CIRCUIT_REJECT.

    When Spec 1 is off OR the auditor is unavailable, fall back to a regex
    bare-number detector as best-effort signal.

    Always degrades gracefully: an exception during the auditor falls back
    to PASS rather than crashing the cascade.
    """
    config = ctx.deps.config
    short_circuit = getattr(config, "cascade_short_circuit_on_stage_a", True)
    pipeline_state = _maybe_pipeline_state(ctx)

    # Path 1: Spec 1 on AND store has products → invoke auditor agent.
    store_products = _store_products(pipeline_state)
    if config.traceability_mode != "off" and store_products:
        try:
            from academic_pipeline.review.agents import agents as _agents

            agent = _agents.get("numerical_claims_auditor")
            if agent is None:
                logger.warning("Stage A: numerical_claims_auditor agent not registered; falling back to regex check")
            else:
                from academic_pipeline.runtime.trace_logger import traced_agent_run

                prompt = _build_auditor_prompt(manuscript, store_products)
                result = await traced_agent_run(
                    agent,
                    prompt,
                    deps=ctx.deps,
                    name="numerical_claims_auditor",
                    phase=PHASE_DIRS[Stage.REVIEW],
                )
                report = result.output
                criticals = [f for f in report.findings if f.severity == "critical"]
                if criticals and short_circuit:
                    return StageResult(
                        stage=CascadeStageName.NUMERICAL_GROUNDING,
                        verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
                        gate_reason=(f"{len(criticals)} numerical claims not grounded in trace store (auditor)."),
                        artifacts={"audit_report": report.model_dump()},
                    )
                return StageResult(
                    stage=CascadeStageName.NUMERICAL_GROUNDING,
                    verdict=StageVerdict.PASS,
                    artifacts={"audit_report": report.model_dump()},
                )
        except Exception as e:  # CSC002 — infra failure, don't block cascade
            logger.warning(
                "Stage A: numerical_claims_auditor failed: %s; falling back to regex check",
                e,
            )

    # Path 2: regex fallback. Looks for bare numbers not wrapped in ⟨num:...⟩.
    bare_count = _count_bare_numbers(manuscript)
    if bare_count > 0 and short_circuit and config.traceability_mode != "off":
        return StageResult(
            stage=CascadeStageName.NUMERICAL_GROUNDING,
            verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
            gate_reason=(
                f"{bare_count} bare numerical values found in prose without ⟨num:label⟩ trace tokens (regex fallback)."
            ),
            artifacts={"bare_number_count": bare_count, "mode": "regex_fallback"},
        )

    return StageResult(
        stage=CascadeStageName.NUMERICAL_GROUNDING,
        verdict=StageVerdict.PASS,
        artifacts={"mode": "regex_fallback" if config.traceability_mode == "off" else "auditor"},
    )


# ---------------------------------------------------------------------------
# Stage B — Novelty
# ---------------------------------------------------------------------------


async def run_novelty_stage(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
) -> StageResult:
    """Stage B: read existing novelty_report from state (populated by Spec 4).

    When Spec 4's PointWiseNoveltyReviewerNode has not run (flag off) the
    state.novelty_report will be None → NOT_RUN. When present, an
    overall_verdict of REJECT_NOVELTY → SHORT_CIRCUIT_REJECT.
    """
    config = ctx.deps.config
    short_circuit = getattr(config, "cascade_short_circuit_on_stage_b", True)

    novelty_report = getattr(ctx.state, "novelty_report", None)
    if novelty_report is None:
        return StageResult(
            stage=CascadeStageName.NOVELTY,
            verdict=StageVerdict.NOT_RUN,
            gate_reason="Spec 4 (pointwise_novelty) disabled or did not run.",
        )

    if novelty_report.overall_verdict == "REJECT_NOVELTY" and short_circuit:
        return StageResult(
            stage=CascadeStageName.NOVELTY,
            verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
            gate_reason=(f"Pointwise novelty rejected: blockers={list(novelty_report.rejection_blockers)}"),
            artifacts={"novelty_report": novelty_report.model_dump()},
        )

    return StageResult(
        stage=CascadeStageName.NOVELTY,
        verdict=StageVerdict.PASS,
        artifacts={"novelty_report": novelty_report.model_dump()},
    )


# ---------------------------------------------------------------------------
# Stage C — Methodology
# ---------------------------------------------------------------------------


async def run_methodology_stage(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
) -> StageResult:
    """Stage C: read persona reviews (Spec 5) and gate on rejection_grounds.

    Senior gatekeeper or methodology purist returning verdict=reject AND any
    finding with rejection_grounds=True → SHORT_CIRCUIT_REJECT
    (when ``config.cascade_short_circuit_on_stage_c`` is true; default false
    per spec — methodology can be salvaged with revision).

    When Spec 5 is off (persona_reviews empty) → NOT_RUN.
    """
    config = ctx.deps.config
    short_circuit = getattr(config, "cascade_short_circuit_on_stage_c", False)

    persona_reviews = list(getattr(ctx.state, "persona_reviews", []) or [])
    if not persona_reviews:
        return StageResult(
            stage=CascadeStageName.METHODOLOGY,
            verdict=StageVerdict.NOT_RUN,
            gate_reason="Spec 5 (persona_reviewers) disabled or did not run.",
        )

    gating_intentions = {"skeptical_gatekeeper", "domain_purist"}
    rejecting: list[str] = []
    for review in persona_reviews:
        intention_value = getattr(getattr(review, "persona", None), "intention", None)
        intention_str = (
            intention_value.value
            if intention_value is not None and hasattr(intention_value, "value")
            else str(intention_value or "")
        )
        if intention_str not in gating_intentions:
            continue
        if review.overall_verdict != "reject":
            continue
        if any(getattr(f, "rejection_grounds", False) for f in review.findings):
            rejecting.append(intention_str)

    if rejecting and short_circuit:
        return StageResult(
            stage=CascadeStageName.METHODOLOGY,
            verdict=StageVerdict.SHORT_CIRCUIT_REJECT,
            gate_reason=(f"Methodology gate rejected by personas: {rejecting} (reject + rejection_grounds finding)."),
            artifacts={"rejecting_personas": rejecting},
        )

    return StageResult(
        stage=CascadeStageName.METHODOLOGY,
        verdict=StageVerdict.PASS,
        artifacts={
            "persona_count": len(persona_reviews),
            "non_short_circuited_rejections": rejecting,
        },
    )


# ---------------------------------------------------------------------------
# Stage D — Narrative quality
# ---------------------------------------------------------------------------


async def run_narrative_stage(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
    manuscript: str,
) -> StageResult:
    """Stage D: terminal narrative quality stage.

    Phase 1: returns PASS unconditionally. Phase 2 will wire this to a
    dedicated narrative scoring agent.
    """
    return StageResult(
        stage=CascadeStageName.NARRATIVE,
        verdict=StageVerdict.PASS,
        gate_reason=None,
        artifacts={"manuscript_length": len(manuscript)},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_pipeline_state(
    ctx: GraphRunContext[ReviewState, PipelineDeps],
) -> Any | None:
    """Best-effort retrieval of the outer PipelineState carried on PipelineDeps.

    The review subgraph runs with ReviewState; the trace store lives on the
    outer PipelineState. PipelineDeps may carry a back-reference under one
    of several attribute names. Returns None if not findable.
    """
    deps = ctx.deps
    for name in ("_pipeline_state", "pipeline_state", "_pipeline_ref"):
        ref = getattr(deps, name, None)
        if ref is None:
            continue
        # Some refs point at the pipeline runner, not the state. Try common
        # accessors.
        state = getattr(ref, "state", ref)
        if hasattr(state, "numerical_store"):
            return state
    return None


def _store_products(pipeline_state: Any | None) -> dict[str, Any]:
    """Return the numerical store's products dict, or empty dict if absent."""
    if pipeline_state is None:
        return {}
    store = getattr(pipeline_state, "numerical_store", None)
    if store is None:
        return {}
    products = getattr(store, "products", None)
    if not isinstance(products, dict):
        return {}
    return products


def _count_bare_numbers(manuscript: str) -> int:
    """Count numbers in the manuscript not wrapped in a ⟨num:label⟩ token.

    Best-effort regex check used by Stage A's fallback path.
    """
    if not manuscript:
        return 0
    # Strip out wrapped tokens before counting bare numbers, so "⟨num:auc⟩"
    # which contains digits in its label doesn't get counted.
    stripped = _TRACE_TOKEN_PATTERN.sub("", manuscript)
    return len(_BARE_NUMBER_PATTERN.findall(stripped))


def _build_auditor_prompt(manuscript: str, products: dict[str, Any]) -> str:
    """Format the prompt sent to the numerical_claims_auditor agent."""
    lines = [
        "Audit the following manuscript's numerical claims against the trace store.",
        "Every numeric value cited in the prose must appear as a ⟨num:label⟩ token",
        "AND the label must resolve to a product in the store.",
        "",
        f"TRACE STORE ({len(products)} products):",
    ]
    for label, product in list(products.items())[:64]:
        value = getattr(product, "value", "")
        unit = getattr(product, "unit", None) or ""
        lines.append(f"  ⟨num:{label}⟩ = {value}{(' ' + unit) if unit else ''}")
    if len(products) > 64:
        lines.append(f"  (... and {len(products) - 64} more products elided)")
    lines.append("")
    lines.append("MANUSCRIPT:")
    lines.append(manuscript)
    return "\n".join(lines)
