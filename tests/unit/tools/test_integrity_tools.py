"""Tests for async integrity tools (PydanticAI-compatible)."""

from __future__ import annotations

import json

import pytest

from academic_pipeline.tools.integrity_tools import (
    check_plagiarism_heuristic,
    detect_ai_style_indicators,
    extract_claims,
)


pytestmark = pytest.mark.anyio


class TestExtractClaims:
    """Tests for the extract_claims async tool."""

    async def test_extracts_claims_from_text(self) -> None:
        text = "AI improves education outcomes. Studies show 30% improvement."
        result = await extract_claims(text)
        assert isinstance(result, str)
        assert len(result) > 0

        parsed = json.loads(result)
        assert parsed["total_claims"] >= 1
        assert any(c["type"] == "numerical" for c in parsed["claims"])

    async def test_handles_empty_text(self) -> None:
        result = await extract_claims("")
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert parsed["total_claims"] == 0
        assert parsed["claims"] == []

    async def test_detects_statistical_claims(self) -> None:
        text = "The treatment group was significantly higher than control (p < 0.05)."
        result = await extract_claims(text)
        parsed = json.loads(result)
        assert parsed["total_claims"] >= 1
        assert any(c["type"] == "statistical" for c in parsed["claims"])

    async def test_detects_causal_claims(self) -> None:
        text = "Increased screen time caused lower test scores."
        result = await extract_claims(text)
        parsed = json.loads(result)
        assert parsed["total_claims"] >= 1
        assert any(c["type"] == "causal" for c in parsed["claims"])

    async def test_detects_categorical_claims(self) -> None:
        text = "All students completed the assessment within the time limit."
        result = await extract_claims(text)
        parsed = json.loads(result)
        assert parsed["total_claims"] >= 1
        assert any(c["type"] == "categorical" for c in parsed["claims"])

    async def test_captures_source_references(self) -> None:
        text = "Studies show 30% improvement (Smith 2024)."
        result = await extract_claims(text)
        parsed = json.loads(result)
        assert parsed["total_claims"] >= 1
        assert len(parsed["claims"][0]["sources_cited"]) >= 1

    async def test_assigns_sequential_claim_ids(self) -> None:
        text = "AI improves 50% of outcomes. All students passed. It caused higher scores."
        result = await extract_claims(text)
        parsed = json.loads(result)
        for i, claim in enumerate(parsed["claims"]):
            assert claim["id"] == f"CLAIM-{i + 1:03d}"


class TestCheckPlagiarism:
    """Tests for the check_plagiarism_heuristic async tool."""

    async def test_returns_analysis(self) -> None:
        text = "This is a test paper about machine learning."
        result = await check_plagiarism_heuristic(text)
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert "paragraphs_analyzed" in parsed
        assert "flags" in parsed
        assert "verdict" in parsed

    async def test_flags_long_uncited_sentences(self) -> None:
        long_sentence = " ".join(["word"] * 25) + "."
        text = f"{long_sentence}\n\nShort paragraph with citation (Smith 2024) that has enough text to be analyzed."
        result = await check_plagiarism_heuristic(text)
        parsed = json.loads(result)
        uncited_flags = [f for f in parsed["flags"] if f["type"] == "potential_uncited_content"]
        assert len(uncited_flags) >= 1

    async def test_short_text_still_runs_ai_checks(self) -> None:
        """Short text still gets AI-style analysis (always returns indicators)."""
        text = "Short text."
        result = await check_plagiarism_heuristic(text)
        parsed = json.loads(result)
        assert parsed["paragraphs_analyzed"] == 0
        assert parsed["flags"] == []
        # ai_style_alerts always present because _detect_ai_patterns returns indicators
        assert "ai_style_alerts" in parsed

    async def test_includes_ai_style_alerts(self) -> None:
        ai_text = (
            "It is important to note that in the realm of research, "
            "we must delve into the nuanced tapestry of knowledge. "
            "This comprehensive study sheds light on the landscape of innovation.\n\n"
            "It is worth noting the multifaceted nature of this work."
        )
        result = await check_plagiarism_heuristic(ai_text)
        parsed = json.loads(result)
        assert "ai_style_alerts" in parsed


class TestDetectAIStyle:
    """Tests for the detect_ai_style_indicators async tool."""

    async def test_returns_analysis(self) -> None:
        text = "Furthermore, it is imperative to note that the aforementioned study."
        result = await detect_ai_style_indicators(text)
        assert isinstance(result, str)

        parsed = json.loads(result)
        assert "indicators_checked" in parsed
        assert "indicators_triggered" in parsed
        assert "flagged" in parsed
        assert "details" in parsed

    async def test_flags_ai_heavy_text(self) -> None:
        ai_text = (
            "It is important to note that in the realm of research, "
            "we must delve into the nuanced tapestry of knowledge. "
            "This comprehensive study sheds light on the landscape of innovation. "
            "It is worth noting the multifaceted nature of this work. "
            "A testament to the underscores the importance of continued inquiry."
        )
        result = await detect_ai_style_indicators(ai_text)
        parsed = json.loads(result)
        phrase_indicator = next(d for d in parsed["details"] if d["indicator"] == "AI high-frequency phrases")
        assert phrase_indicator["triggered"] is True

    async def test_clean_text_not_flagged(self) -> None:
        text = "The experiment measured reaction times across three conditions."
        result = await detect_ai_style_indicators(text)
        parsed = json.loads(result)
        assert parsed["flagged"] is False

    async def test_includes_heuristic_note(self) -> None:
        result = await detect_ai_style_indicators("Any text.")
        parsed = json.loads(result)
        assert "heuristic" in parsed["note"].lower()

    async def test_checks_six_indicators(self) -> None:
        result = await detect_ai_style_indicators("Sample text for analysis.")
        parsed = json.loads(result)
        assert parsed["indicators_checked"] == 6
