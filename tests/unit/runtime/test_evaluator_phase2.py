"""Phase-2 evaluator regression tests — PRD §6.11.T6.

Five named tests required by PRD §6.11.T6, all anchored at this path so the
evaluator's quality-gate contract has a single drift detector. Most exercise
functions whose deeper unit coverage lives elsewhere (the modules that
shipped each piece in §6.11.T1, §6.11.T2, §6.12.T5); this file is the
integration-level guard.

Inventory:
1. hedge-language veto fires on output through apply_hard_vetos
2. missing-trace-token veto fires on bare percentages/decimals
3. per-node threshold map honored via PipelineConfig.get_node_threshold
4. [PENDING:] carve-out preserved (AP56 regression)
5. scores preserved unchanged on hard veto (AP57 regression)
"""

from __future__ import annotations

from academic_pipeline.config import PipelineConfig
from academic_pipeline.models.shared import EvaluationResult
from academic_pipeline.runtime.hard_vetos import (
    aborting_phrase_present,
    apply_hard_vetos,
    hedge_near_trace_token,
    missing_trace_token,
    no_placeholder_tokens,
)


def _passing(scores: dict[str, float] | None = None) -> EvaluationResult:
    return EvaluationResult(
        verdict="PASS",
        scores=scores or {"depth": 9.0, "rigor": 8.5, "clarity": 7.7},
        feedback="ok",
        weakest_dimension=None,
    )


def test_hedge_language_veto_fires_through_apply_hard_vetos() -> None:
    """hedge_near_trace_token wired through apply_hard_vetos forces NEEDS_IMPROVEMENT."""
    text = "The accuracy was approximately ⟨num:acc⟩ on the test set."
    result = apply_hard_vetos(text, _passing(), [hedge_near_trace_token])
    assert result.verdict == "NEEDS_IMPROVEMENT"
    assert "approximately" in result.feedback.lower()


def test_missing_trace_token_veto_fires_on_bare_percentage() -> None:
    """missing_trace_token catches numeric content without a ⟨num:label⟩ wrapper."""
    text = "Reported accuracy: 87.5% on holdout."
    result = apply_hard_vetos(text, _passing(), [missing_trace_token])
    assert result.verdict == "NEEDS_IMPROVEMENT"
    assert "trace token" in result.feedback.lower()


def test_per_node_threshold_map_honored() -> None:
    """PipelineConfig.get_node_threshold returns per-node value, falls back to global.

    Mirrors the §6.12.T5 unit tests at the integration boundary so a refactor
    of the evaluator wiring can't silently bypass the per-node map.
    """
    cfg = PipelineConfig(
        anthropic_api_key="sk-test",
        node_quality_threshold=7.0,
        node_quality_thresholds={"draft_writer": 8.5, "synthesis": 6.0},
    )
    assert cfg.get_node_threshold("draft_writer") == 8.5
    assert cfg.get_node_threshold("synthesis") == 6.0
    # Unknown node falls back to global default.
    assert cfg.get_node_threshold("unknown_node") == 7.0


def test_pending_carve_out_preserved_ap56_regression() -> None:
    """[PENDING:] is the SANCTIONED deferral marker — must not be vetoed (AP56)."""
    text = "Citation [PENDING: literature search] will be filled in after intake."

    # Both the placeholder veto and the aborting-phrase veto must let
    # [PENDING:] through.
    assert no_placeholder_tokens(text) is None
    assert aborting_phrase_present(text) is None

    # And running both vetos via the gate must produce a clean PASS.
    result = apply_hard_vetos(text, _passing(), [no_placeholder_tokens, aborting_phrase_present])
    assert result.verdict == "PASS"


def test_scores_preserved_on_hard_veto_ap57_regression() -> None:
    """apply_hard_vetos must NEVER mutate EvaluationResult.scores (AP57)."""
    original_scores = {"depth": 9.0, "rigor": 8.5, "clarity": 7.7, "originality": 8.0}
    original = _passing(scores=dict(original_scores))

    # Force a veto fire — accuracy of preservation is independent of which
    # veto triggers, so use the most explicit one.
    result = apply_hard_vetos(
        "Section body has [insert TODO here] placeholder text.",
        original,
        [aborting_phrase_present],
    )
    assert result.verdict == "NEEDS_IMPROVEMENT"
    # Byte-equal scores dict — AP57.
    assert result.scores == original_scores
    # Original object's scores also unmodified (defensive copy verification).
    assert original.scores == original_scores
