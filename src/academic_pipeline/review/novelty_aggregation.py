"""Pure aggregation function for the point-wise novelty reviewer (SCI Spec 4 Phase 1).

Maps a list of per-claim assessments to a NoveltyReport with overall_verdict
and rejection_blockers. Pure: no I/O, no side effects.
"""

from __future__ import annotations

from academic_pipeline.models.novelty_report import (
    ClaimAssessment,
    ClaimVerdict,
    ContributionClaim,
    NoveltyReport,
)


def aggregate_novelty_report(
    claims: list[ContributionClaim],
    assessments: list[ClaimAssessment],
) -> NoveltyReport:
    """Aggregate per-claim assessments into a NoveltyReport.

    Verdict precedence:
    - any verdict==REDUNDANT → REJECT_NOVELTY (blockers list those claim_ids)
    - else any PARTIAL_OVERLAP → REVISE (writer must add differentiation)
    - else → PASS
    """
    blockers = [a.claim_id for a in assessments if a.verdict == ClaimVerdict.REDUNDANT]
    if blockers:
        overall: str = "REJECT_NOVELTY"
    elif any(a.verdict == ClaimVerdict.PARTIAL_OVERLAP for a in assessments):
        overall = "REVISE"
    else:
        overall = "PASS"
    return NoveltyReport(
        claims=claims,
        assessments=assessments,
        overall_verdict=overall,  # type: ignore[arg-type]
        rejection_blockers=blockers,
    )
