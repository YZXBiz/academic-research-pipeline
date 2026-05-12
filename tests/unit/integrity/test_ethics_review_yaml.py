"""Tests for the ethics_review.yaml prompt content."""

from __future__ import annotations

from pathlib import Path


def _yaml_text() -> str:
    return Path("src/academic_pipeline/integrity/specs/ethics_review.yaml").read_text()


def test_yaml_loads_via_pydantic_ai() -> None:
    from pydantic_ai import Agent

    agent = Agent.from_file("src/academic_pipeline/integrity/specs/ethics_review.yaml")
    assert agent is not None


def test_yaml_requires_structural_coi_analysis() -> None:
    text = _yaml_text().lower()
    # Must require cross-referencing source verification COI flags
    assert "source verification" in text or "self-eval" in text or "structural" in text
    assert "coi" in text or "conflict of interest" in text


def test_yaml_requires_substantive_fairness_engagement() -> None:
    text = _yaml_text()
    # Must mention specific fairness concepts, not just "fairness"
    assert "Obermeyer" in text or "algorithmic bias" in text or "race-based" in text or "allocation harm" in text


def test_yaml_requires_substantive_dual_use_engagement() -> None:
    text = _yaml_text().lower()
    # Must require more than one-liner
    assert "deployment risk" in text or "automation bias" in text or "false confidence" in text


def test_yaml_requires_evidence_citation_per_dimension() -> None:
    text = _yaml_text().lower()
    # Must require quoted evidence per dimension
    assert "evidence" in text
    assert "quoted" in text or "quote" in text or "specific" in text
