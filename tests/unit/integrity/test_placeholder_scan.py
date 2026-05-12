"""Tests for placeholder_scan.py — deterministic placeholder detection."""
from __future__ import annotations

from academic_pipeline.integrity.placeholder_scan import (
    PlaceholderFinding,
    format_findings_report,
    scan_placeholders,
)


def test_empty_text_returns_no_findings() -> None:
    assert scan_placeholders("") == []


def test_clean_text_returns_no_findings() -> None:
    text = "This is a normal paper. It cites [smith2024] and reports AUC=0.87."
    assert scan_placeholders(text) == []


def test_prospero_placeholder_detected() -> None:
    text = "Protocol registered at PROSPERO (CRD42024-XXXXXX)."
    findings = scan_placeholders(text)
    assert len(findings) == 1
    assert findings[0].label == "PROSPERO placeholder"
    assert findings[0].severity == "BLOCKING"
    assert findings[0].match == "CRD42024-XXXXXX"


def test_prospero_no_dash_variant_detected() -> None:
    text = "Registration: CRD42025XXXXXX prior to screening."
    findings = scan_placeholders(text)
    assert len(findings) == 1
    assert findings[0].label == "PROSPERO placeholder"


def test_real_prospero_id_not_flagged() -> None:
    """A legitimate 8-digit-plus-six-more PROSPERO ID without X must NOT match."""
    text = "Registered as CRD42024123456 in PROSPERO."
    assert scan_placeholders(text) == []


def test_clinicaltrials_placeholder_detected() -> None:
    text = "Trial: NCT0XXXXX."
    findings = scan_placeholders(text)
    assert len(findings) == 1
    assert findings[0].label == "ClinicalTrials.gov placeholder"


def test_generic_xxxx_placeholder_detected() -> None:
    text = "Author: XXXXX redacted."
    findings = scan_placeholders(text)
    assert len(findings) == 1
    assert findings[0].label == "Generic XXXX placeholder"


def test_tbd_marker_detected() -> None:
    findings = scan_placeholders("Effect size TBD pending analysis.")
    assert any(f.label == "TBD marker" and f.severity == "BLOCKING" for f in findings)


def test_todo_marker_detected() -> None:
    findings = scan_placeholders("TODO: write conclusion.")
    assert any(f.label == "TODO marker" for f in findings)


def test_redacted_placeholder_detected() -> None:
    findings = scan_placeholders("Author affiliation: [redacted]")
    assert any(f.label == "Redaction placeholder" for f in findings)


def test_insert_placeholder_detected() -> None:
    findings = scan_placeholders("[INSERT corresponding author email]")
    assert any(f.label == "INSERT placeholder" for f in findings)


def test_pending_marker_classified_as_pending_not_blocking() -> None:
    text = "Pooled estimate: [PENDING: ΔAUROC from full meta-analysis]"
    findings = scan_placeholders(text)
    assert len(findings) == 1
    assert findings[0].severity == "PENDING"
    assert findings[0].label == "Pending value"


def test_multiple_findings_report_correct_line_numbers() -> None:
    text = "line 1\nCRD42024-XXXXXX\nline 3\nTBD on line 4"
    findings = scan_placeholders(text)
    lines = {f.line for f in findings}
    assert 2 in lines
    assert 4 in lines


def test_format_findings_report_empty_state() -> None:
    out = format_findings_report([])
    assert "No placeholders" in out
    assert "## Placeholder Scan" in out


def test_format_findings_report_with_findings() -> None:
    findings = [
        PlaceholderFinding(
            pattern=r"\bTBD\b", label="TBD marker", match="TBD",
            line=42, severity="BLOCKING",
        )
    ]
    out = format_findings_report(findings)
    assert "TBD" in out
    assert "BLOCKING" in out
    assert "42" in out
    assert "## Placeholder Scan" in out
