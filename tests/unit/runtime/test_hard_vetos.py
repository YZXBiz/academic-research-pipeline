"""Tests for code-enforced hard-veto patterns."""

from __future__ import annotations

from academic_pipeline.models.shared import EvaluationResult
from academic_pipeline.runtime.hard_vetos import (
    apply_hard_vetos,
    no_bare_latex_commands,
    no_placeholder_tokens,
)


def _passing() -> EvaluationResult:
    return EvaluationResult(
        verdict="PASS",
        scores={"depth": 9.0, "citations": 8.5},
        feedback="ok",
        weakest_dimension=None,
    )


class TestPlaceholderVeto:
    def test_clean_text_no_veto(self) -> None:
        assert no_placeholder_tokens("Normal sentence with [smith2020] cite.") is None

    def test_xxx_run_caught(self) -> None:
        msg = no_placeholder_tokens("Registered as CRD42024-XXXXXX.")
        assert msg is not None
        assert "CRD42024-XXXXXX" in msg

    def test_prospero_with_keyword_caught(self) -> None:
        msg = no_placeholder_tokens("(PROSPERO CRD42024-XXXXXX)")
        assert msg is not None

    def test_nct_placeholder_caught(self) -> None:
        msg = no_placeholder_tokens("Trial NCT0XXXXXXX is registered.")
        assert msg is not None

    def test_redacted_caught(self) -> None:
        msg = no_placeholder_tokens("see https://github.com/[redacted]")
        assert msg is not None
        assert "[redacted]" in msg

    def test_insert_marker_caught(self) -> None:
        msg = no_placeholder_tokens("Add [INSERT CITATION HERE] later.")
        assert msg is not None

    def test_todo_caught(self) -> None:
        msg = no_placeholder_tokens("Method TODO: complete this.")
        assert msg is not None

    def test_tbd_caught(self) -> None:
        msg = no_placeholder_tokens("Results: TBD.")
        assert msg is not None

    def test_dangling_bold_caught(self) -> None:
        msg = no_placeholder_tokens("Background.\n**Ob")
        assert msg is not None
        assert "**Ob" in msg

    def test_pending_marker_not_treated_as_placeholder(self) -> None:
        # [PENDING: ...] is the SANCTIONED form for explicit deferrals
        # (per section_writer.yaml). Must NOT be vetoed.
        assert no_placeholder_tokens("[PENDING: PROSPERO registration ID]") is None


class TestBareLatexVeto:
    def test_clean_unicode_no_veto(self) -> None:
        assert no_bare_latex_commands("correlation ρ = 0.5") is None  # noqa: RUF001 — Greek rho is intentional

    def test_wrapped_math_no_veto(self) -> None:
        assert no_bare_latex_commands(r"correlation $\rho = 0.5$") is None

    def test_bare_greek_caught(self) -> None:
        msg = no_bare_latex_commands(r"correlation \rho = 0.5")
        assert msg is not None
        assert r"\rho" in msg

    def test_bare_capital_greek_caught(self) -> None:
        msg = no_bare_latex_commands(r"\Delta AUROC = 0.014")
        assert msg is not None
        assert r"\Delta" in msg

    def test_bare_relation_caught(self) -> None:
        msg = no_bare_latex_commands(r"x \leq 5")
        assert msg is not None

    def test_text_command_not_caught(self) -> None:
        # \textbf is a text-mode command, not a math command — should not veto
        assert no_bare_latex_commands(r"This is \textbf{bold} text.") is None

    def test_unknown_command_not_caught(self) -> None:
        # \foobar is not in the math command whitelist — should not veto
        assert no_bare_latex_commands(r"\foobar is not a math command") is None

    def test_multiple_bare_commands_caught(self) -> None:
        msg = no_bare_latex_commands(r"\tau^2 = 0.041 and \Delta AUROC = 0.014")
        assert msg is not None
        # Both reported
        assert r"\tau" in msg
        assert r"\Delta" in msg


class TestApplyHardVetos:
    def test_no_vetos_passes_through(self) -> None:
        result = apply_hard_vetos("Clean text.", _passing(), [no_placeholder_tokens])
        assert result.verdict == "PASS"

    def test_veto_overrides_pass(self) -> None:
        result = apply_hard_vetos(
            "Reg id CRD42024-XXXXXX.",
            _passing(),
            [no_placeholder_tokens],
        )
        assert result.verdict == "NEEDS_IMPROVEMENT"
        assert "CRD42024-XXXXXX" in result.feedback
        assert result.weakest_dimension == "hard_veto"

    def test_veto_preserves_scores(self) -> None:
        passing = _passing()
        result = apply_hard_vetos(
            "Reg id CRD42024-XXXXXX.",
            passing,
            [no_placeholder_tokens],
        )
        # Scores from the LLM rubric are preserved (informational); only
        # verdict/feedback/weakest_dimension are overridden.
        assert result.scores == passing.scores

    def test_multiple_vetos_run_all_reasons_appended(self) -> None:
        result = apply_hard_vetos(
            r"CRD42024-XXXXXX uses \rho",
            _passing(),
            [no_placeholder_tokens, no_bare_latex_commands],
        )
        assert result.verdict == "NEEDS_IMPROVEMENT"
        assert "CRD42024-XXXXXX" in result.feedback
        assert r"\rho" in result.feedback

    def test_existing_needs_improvement_unchanged_if_no_veto(self) -> None:
        existing = EvaluationResult(
            verdict="NEEDS_IMPROVEMENT",
            scores={"depth": 4.0},
            feedback="needs more depth",
            weakest_dimension="depth",
        )
        result = apply_hard_vetos("Clean text.", existing, [no_placeholder_tokens])
        # No veto fired → existing result returned unchanged
        assert result.verdict == "NEEDS_IMPROVEMENT"
        assert result.feedback == "needs more depth"
        assert result.weakest_dimension == "depth"

    def test_existing_needs_improvement_appends_veto_reason(self) -> None:
        existing = EvaluationResult(
            verdict="NEEDS_IMPROVEMENT",
            scores={"depth": 4.0},
            feedback="needs more depth",
            weakest_dimension="depth",
        )
        result = apply_hard_vetos(
            "CRD42024-XXXXXX",
            existing,
            [no_placeholder_tokens],
        )
        assert result.verdict == "NEEDS_IMPROVEMENT"
        # Veto reason appended to existing feedback
        assert "needs more depth" in result.feedback
        assert "CRD42024-XXXXXX" in result.feedback

    def test_empty_veto_list_passes_through(self) -> None:
        result = apply_hard_vetos("anything", _passing(), [])
        assert result.verdict == "PASS"


# PRD §6.11.T2 — hedge phrases near trace tokens + aborting phrases anywhere.


class TestHedgeNearTraceToken:
    """5 hedge phrases (validators.py:37-39) within HEDGE_PROXIMITY_TOKENS BEFORE ⟨num:label⟩."""

    def test_clean_text_passes(self) -> None:
        from academic_pipeline.runtime.hard_vetos import hedge_near_trace_token

        assert hedge_near_trace_token("The result was ⟨num:p_value⟩.") is None

    def test_hedge_immediately_before_trace_token_fires(self) -> None:
        from academic_pipeline.runtime.hard_vetos import hedge_near_trace_token

        for hedge in ("approximately", "around", "roughly", "circa", "~"):
            text = f"The accuracy was {hedge} ⟨num:acc⟩ on the test set."
            reason = hedge_near_trace_token(text)
            assert reason is not None, f"hedge {hedge!r} should fire"
            assert hedge in reason

    def test_hedge_after_trace_token_does_not_fire(self) -> None:
        """Direction matters — hedge BEFORE the token only (per Spec 1)."""
        from academic_pipeline.runtime.hard_vetos import hedge_near_trace_token

        assert hedge_near_trace_token("Reported ⟨num:acc⟩ approximately later.") is None

    def test_hedge_far_from_trace_token_does_not_fire(self) -> None:
        """Beyond HEDGE_PROXIMITY_TOKENS (default 5) the hedge is not flagged."""
        from academic_pipeline.runtime.hard_vetos import hedge_near_trace_token

        # 12 filler tokens between hedge and the trace token — well past 5.
        text = "Roughly " + " ".join(["filler"] * 12) + " ⟨num:acc⟩"
        assert hedge_near_trace_token(text) is None

    def test_no_trace_token_means_no_veto(self) -> None:
        from academic_pipeline.runtime.hard_vetos import hedge_near_trace_token

        assert hedge_near_trace_token("Roughly half of all participants completed.") is None


class TestAbortingPhrasePresent:
    """9 aborting phrases (validators.py:42-45), case-insensitive, anywhere in body."""

    def test_clean_text_passes(self) -> None:
        from academic_pipeline.runtime.hard_vetos import aborting_phrase_present

        assert aborting_phrase_present("Standard manuscript content.") is None

    def test_each_aborting_phrase_fires(self) -> None:
        from academic_pipeline.runtime.hard_vetos import aborting_phrase_present

        for phrase in (
            "[insert",
            "[unknown",
            "[to be determined",
            "[to be",
            "subject to revision",
            "pending full search",
            "<insert",
            "<unknown",
            "<missing",
        ):
            text = f"Section body has {phrase} placeholder text."
            reason = aborting_phrase_present(text)
            assert reason is not None, f"aborting phrase {phrase!r} should fire"

    def test_case_insensitive(self) -> None:
        from academic_pipeline.runtime.hard_vetos import aborting_phrase_present

        assert aborting_phrase_present("This is Subject To Revision pending edits.") is not None

    def test_pending_carve_out_preserved(self) -> None:
        """[PENDING:] is the SANCTIONED form per AP56 — must not be vetoed."""
        from academic_pipeline.runtime.hard_vetos import aborting_phrase_present

        # Sanctioned deferral marker — should not fire.
        assert aborting_phrase_present("Deferred citation [PENDING: literature search]") is None


class TestHedgeAndAbortingScoresPreserved:
    """Per AP57 — apply_hard_vetos must NEVER mutate EvaluationResult.scores."""

    def test_scores_preserved_when_hedge_veto_fires(self) -> None:
        from academic_pipeline.runtime.hard_vetos import (
            apply_hard_vetos,
            hedge_near_trace_token,
        )

        original = EvaluationResult(
            verdict="PASS",
            scores={"depth": 9.0, "citations": 8.5, "rigor": 7.7},
            feedback="ok",
            weakest_dimension=None,
        )
        result = apply_hard_vetos(
            "Accuracy was approximately ⟨num:acc⟩",
            original,
            [hedge_near_trace_token],
        )
        assert result.verdict == "NEEDS_IMPROVEMENT"
        # Scores dict must round-trip byte-equal — AP57.
        assert result.scores == original.scores
