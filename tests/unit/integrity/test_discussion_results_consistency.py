"""Tests for the Discussion-vs-Results consistency scanner.

Catches the failure class from run-0511-2107: the Discussion section
confidently interprets quantitative findings ("the correlation was robust
and persistent", "the effect size was moderate") while the Results section
is entirely `[PENDING:]` placeholders — the paper narrates results it does
not have.

The check only fires when BOTH conditions hold:
  1. the Results section is substantially unpopulated (has [PENDING:] markers)
  2. the Discussion section asserts magnitude/direction findings
A populated Results section means Discussion is interpreting real data — fine.
"""

from __future__ import annotations

from academic_pipeline.integrity.discussion_results_consistency import (
    ConsistencyFinding,
    format_consistency_report,
    scan_discussion_results,
)


# --- The core contradiction: empty Results + asserted findings in Discussion ---


class TestFiresOnFabricatedInterpretation:
    def test_moderate_effect_claim_with_pending_results(self) -> None:
        text = """# Results

The correlation was [PENDING: r] (p [PENDING: p]).

# Discussion

The effect size was moderate, tempering overly optimistic interpretations.
"""
        findings = scan_discussion_results(text)
        assert len(findings) >= 1
        assert any("moderate" in f.claim_text for f in findings)
        assert all(f.severity == "BLOCKING" for f in findings)

    def test_robust_persistent_correlation_claim(self) -> None:
        text = """# Results

Testing frequency showed a [PENDING: magnitude] correlation ($r = [PENDING: r]$).

# Discussion

The correlation between testing frequency and quality was robust and persistent
even after controlling for covariates.
"""
        findings = scan_discussion_results(text)
        assert len(findings) >= 1
        assert any("robust" in f.claim_text for f in findings)

    def test_significant_predictor_claim(self) -> None:
        text = """# Results

Step 2 added testing frequency ($\\beta = [PENDING: beta]$).

# Discussion

Organizational support was a significant predictor of adoption in our models.
"""
        findings = scan_discussion_results(text)
        assert len(findings) >= 1

    def test_multiple_claims_each_flagged(self) -> None:
        text = """# Results

Mean was [PENDING: M] (SD = [PENDING: SD]).

# Discussion

The effect size was moderate. The association was strong and consistent.
"""
        findings = scan_discussion_results(text)
        # Two distinct magnitude-claim sentences.
        assert len(findings) == 2


# --- Must NOT fire when Results is real or Discussion is honest ---


class TestDoesNotFireWhenResultsArePopulated:
    def test_populated_results_with_moderate_claim_is_fine(self) -> None:
        """Discussion interpreting REAL results is exactly what a Discussion is for."""
        text = """# Results

Testing frequency correlated with perceived quality ($r = 0.42$, $p < .001$).

# Discussion

The effect size was moderate, consistent with prior work.
"""
        findings = scan_discussion_results(text)
        assert findings == []

    def test_pending_results_but_hedged_discussion_is_fine(self) -> None:
        """A Discussion that only proposes future work makes no findings claims."""
        text = """# Results

The sample yielded [PENDING: N] responses.

# Discussion

Future work should examine longitudinal trends. Replication across sectors
would strengthen confidence in any observed pattern.
"""
        findings = scan_discussion_results(text)
        assert findings == []


# --- Graceful degradation on missing sections ---


class TestMissingSections:
    def test_no_results_section_returns_empty(self) -> None:
        text = """# Discussion

The effect size was moderate.
"""
        assert scan_discussion_results(text) == []

    def test_no_discussion_section_returns_empty(self) -> None:
        text = """# Results

Mean was [PENDING: M].
"""
        assert scan_discussion_results(text) == []

    def test_empty_text_returns_empty(self) -> None:
        assert scan_discussion_results("") == []


# --- Section boundary handling ---


class TestSectionBoundaries:
    def test_discussion_claim_after_results_section_ends(self) -> None:
        """Magnitude language in a LATER section (Conclusion) is still the Discussion's
        problem only if it's under Discussion — Conclusion claims are out of scope here."""
        text = """# Results

Value [PENDING: x].

# Discussion

The effect was moderate.

# Conclusion

The effect was strong and robust.
"""
        findings = scan_discussion_results(text)
        # Only the Discussion-section claim, not the Conclusion one.
        assert len(findings) == 1
        assert "moderate" in findings[0].claim_text

    def test_subsection_headings_within_discussion_are_included(self) -> None:
        text = """# Results

Value [PENDING: x].

# Discussion

## Interpretation of Findings

The correlation was robust.
"""
        findings = scan_discussion_results(text)
        assert len(findings) == 1


# --- Report formatting ---


class TestReportFormatting:
    def test_empty_findings_report(self) -> None:
        report = format_consistency_report([])
        assert "Discussion" in report
        assert "no" in report.lower() or "No" in report

    def test_findings_report_lists_each_claim(self) -> None:
        findings = [
            ConsistencyFinding(claim_text="The effect was moderate.", line=7, severity="BLOCKING"),
        ]
        report = format_consistency_report(findings)
        assert "moderate" in report
        assert "BLOCKING" in report
