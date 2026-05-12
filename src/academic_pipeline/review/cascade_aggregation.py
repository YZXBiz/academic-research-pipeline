"""Aggregation helper for the cascaded reviewer pipeline (SCI Spec 6 Phase 1).

Given the ordered list of stage results that the CascadedReviewNode emitted,
build the final CascadeResult: derive final_verdict, rejection_stage, and a
short rejection_summary from the first SHORT_CIRCUIT_REJECT (if any).
"""

from __future__ import annotations

from academic_pipeline.models.cascade import (
    CascadeResult,
    CascadeStageName,
    StageResult,
    StageVerdict,
)


# Always-emit ordering of cascade stages, used to pad with SKIPPED entries
# when an earlier stage rejected.
_STAGE_ORDER: tuple[CascadeStageName, ...] = (
    CascadeStageName.NUMERICAL_GROUNDING,
    CascadeStageName.NOVELTY,
    CascadeStageName.METHODOLOGY,
    CascadeStageName.NARRATIVE,
)


def aggregate_cascade_result(stages: list[StageResult]) -> CascadeResult:
    """Build the final CascadeResult from completed stages.

    Rules:
      - First stage with verdict=SHORT_CIRCUIT_REJECT → final_verdict=reject;
        rejection_stage = that stage; subsequent stages padded as SKIPPED.
      - Otherwise → final_verdict=accept; pad any unvisited trailing stages
        as SKIPPED so the result always carries an entry per stage in order.

    Phase 1: this is purely structural; Phase 2 will plumb the verdict into
    EditorialSynthesizerNode.
    """
    visited_by_stage = {s.stage: s for s in stages}

    # Find the first SHORT_CIRCUIT_REJECT in run order.
    rejection_stage: CascadeStageName | None = None
    rejection_summary = ""
    for stage_name in _STAGE_ORDER:
        result = visited_by_stage.get(stage_name)
        if result is None:
            continue
        if result.verdict == StageVerdict.SHORT_CIRCUIT_REJECT:
            rejection_stage = stage_name
            rejection_summary = (
                result.gate_reason
                or f"Cascade rejected at stage {stage_name.value}."
            )
            break

    # Pad to one entry per stage in canonical order.
    padded: list[StageResult] = []
    seen_rejection = False
    for stage_name in _STAGE_ORDER:
        result = visited_by_stage.get(stage_name)
        if result is not None:
            padded.append(result)
            if result.verdict == StageVerdict.SHORT_CIRCUIT_REJECT:
                seen_rejection = True
        else:
            # Unvisited stage. If a prior stage rejected, mark SKIPPED;
            # otherwise NOT_RUN (the upstream flag was likely off).
            verdict = StageVerdict.SKIPPED if seen_rejection else StageVerdict.NOT_RUN
            padded.append(
                StageResult(stage=stage_name, verdict=verdict, gate_reason=None)
            )

    final_verdict = "reject" if rejection_stage is not None else "accept"
    return CascadeResult(
        stages=padded,
        final_verdict=final_verdict,
        rejection_stage=rejection_stage,
        rejection_summary=rejection_summary,
    )
