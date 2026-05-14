"""Tests for methodology-aware reporting-guideline selection.

run-0511-2107 close-read, Bug 4: the compliance check ran the PRISMA-trAIce
*AI-use disclosure* checklist and nothing else, so for a survey paper every
study-design reporting item came back not_applicable and the check
contributed nothing. The fix detects the paper's study design from its
Methods section and appends the matching reporting guideline's core items
(CHERRIES for surveys, STROBE for observational, CONSORT for trials,
PRISMA for systematic reviews).
"""

from __future__ import annotations

from academic_pipeline.integrity.reporting_guidelines import (
    StudyDesign,
    build_compliance_prompt,
    design_reporting_items,
    detect_study_design,
)


class TestDetectStudyDesign:
    def test_survey_paper(self) -> None:
        text = """# Methodology

        We administered a cross-sectional survey. The questionnaire used
        five-point Likert scales and was distributed to industry respondents.
        """
        assert detect_study_design(text) is StudyDesign.SURVEY

    def test_systematic_review(self) -> None:
        text = """# Methods

        We conducted a systematic review following PRISMA. The search strategy
        covered four databases with explicit inclusion criteria.
        """
        assert detect_study_design(text) is StudyDesign.SYSTEMATIC_REVIEW

    def test_experimental_rct(self) -> None:
        text = """# Methods

        Participants were randomized to a treatment group and a control group.
        This randomized controlled trial used allocation concealment.
        """
        assert detect_study_design(text) is StudyDesign.EXPERIMENTAL

    def test_observational_cohort(self) -> None:
        text = """# Methods

        We followed a retrospective cohort over five years in an observational
        design, with no intervention assigned.
        """
        assert detect_study_design(text) is StudyDesign.OBSERVATIONAL

    def test_unknown_when_no_signal(self) -> None:
        text = """# Methods

        We thought carefully about the problem and wrote down our reflections.
        """
        assert detect_study_design(text) is StudyDesign.UNKNOWN

    def test_systematic_review_beats_survey_when_both_appear(self) -> None:
        """A systematic review *of* surveys is still a systematic review."""
        text = """# Methods

        We conducted a systematic review and meta-analysis of survey-based
        questionnaire studies, with a documented search strategy.
        """
        assert detect_study_design(text) is StudyDesign.SYSTEMATIC_REVIEW

    def test_experimental_beats_survey(self) -> None:
        """An RCT that collects outcomes via questionnaire is still an RCT."""
        text = """# Methods

        In this randomized controlled trial, outcomes were measured with a
        post-intervention questionnaire administered to both arms.
        """
        assert detect_study_design(text) is StudyDesign.EXPERIMENTAL

    def test_detects_in_methodology_heading_variant(self) -> None:
        """Section heading may be 'Methodology' or 'Methods' or 'Materials and Methods'."""
        text = """# Materials and Methods

        A survey questionnaire with Likert items was used.
        """
        assert detect_study_design(text) is StudyDesign.SURVEY

    def test_no_methods_section_scans_whole_text(self) -> None:
        """When there's no Methods heading, fall back to scanning the whole document."""
        text = "This paper reports a randomized controlled trial of a new tool."
        assert detect_study_design(text) is StudyDesign.EXPERIMENTAL


class TestDesignReportingItems:
    def test_survey_returns_cherries_items(self) -> None:
        items = design_reporting_items(StudyDesign.SURVEY)
        lowered = items.lower()
        assert "cherries" in lowered
        assert "response rate" in lowered

    def test_systematic_review_returns_prisma_items(self) -> None:
        items = design_reporting_items(StudyDesign.SYSTEMATIC_REVIEW)
        assert "PRISMA" in items
        assert "search strategy" in items.lower()

    def test_experimental_returns_consort_items(self) -> None:
        items = design_reporting_items(StudyDesign.EXPERIMENTAL)
        lowered = items.lower()
        assert "consort" in lowered
        assert "randomi" in lowered  # randomization / randomisation

    def test_observational_returns_strobe_items(self) -> None:
        items = design_reporting_items(StudyDesign.OBSERVATIONAL)
        assert "STROBE" in items

    def test_unknown_returns_generic_items(self) -> None:
        items = design_reporting_items(StudyDesign.UNKNOWN)
        # Generic fallback still asks for the universally-required basics.
        assert "study design" in items.lower()
        assert "limitations" in items.lower()

    def test_every_design_yields_nonempty_checklist(self) -> None:
        for design in StudyDesign:
            assert design_reporting_items(design).strip() != ""


class TestBuildCompliancePrompt:
    """The prompt composes the (methodology-agnostic) AI-disclosure checklist
    with the methodology-detected study-design reporting items."""

    _AI_DISCLOSURE = "AI-USE DISCLOSURE CHECKLIST:\n- D1 Tool identification\n- D2 Human oversight"

    def test_survey_paper_prompt_includes_cherries(self) -> None:
        draft = """# Methods

        We administered a Likert-scale questionnaire survey to respondents.
        """
        prompt = build_compliance_prompt(self._AI_DISCLOSURE, draft, "2.5")
        assert "AI-USE DISCLOSURE CHECKLIST" in prompt  # disclosure checklist always present
        assert "CHERRIES" in prompt  # study-design items routed by methodology
        assert "response rate" in prompt.lower()

    def test_systematic_review_prompt_includes_prisma_items(self) -> None:
        draft = """# Methods

        A systematic review with a documented search strategy across databases.
        """
        prompt = build_compliance_prompt(self._AI_DISCLOSURE, draft, "2.5")
        assert "PRISMA core reporting items" in prompt

    def test_prompt_carries_the_paper_text_and_stage(self) -> None:
        draft = "# Methods\n\nA randomized controlled trial.\n\nUNIQUE_PAPER_MARKER_42"
        prompt = build_compliance_prompt(self._AI_DISCLOSURE, draft, "4.5")
        assert "UNIQUE_PAPER_MARKER_42" in prompt
        assert "4.5" in prompt

    def test_unknown_design_still_produces_a_prompt(self) -> None:
        draft = "# Methods\n\nWe reflected on the literature."
        prompt = build_compliance_prompt(self._AI_DISCLOSURE, draft, "2.5")
        assert "AI-USE DISCLOSURE CHECKLIST" in prompt
        assert "Generic minimal-reporting items" in prompt
