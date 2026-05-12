"""Tests for report_compiler evaluation rubric."""
from __future__ import annotations

from academic_pipeline.research.graph import _RUBRIC_REPORT


def test_rubric_report_exists():
    assert _RUBRIC_REPORT is not None
    assert "Completeness" in _RUBRIC_REPORT
    assert "Coherence" in _RUBRIC_REPORT
    assert "Evidence quality" in _RUBRIC_REPORT
    assert "10 means genuinely world-class" in _RUBRIC_REPORT
