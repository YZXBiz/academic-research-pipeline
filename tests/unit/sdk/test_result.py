"""Tests for PipelineResult save and artifact serialization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from academic_pipeline.sdk.result import PipelineResult


if TYPE_CHECKING:
    from pathlib import Path


class TestPipelineResultSave:
    def test_save_creates_output_dir(self, tmp_path):
        r = PipelineResult({"topic": "AI"})
        out = r.save(tmp_path / "new_dir")
        assert out.exists()
        assert out.is_dir()

    def test_save_writes_paper_draft(self, tmp_path):
        r = PipelineResult({"topic": "AI", "paper_draft": {"title": "My Paper", "content": "# My Paper\nContent"}})
        out = r.save(tmp_path / "output")
        assert (out / "02-writing" / "artifacts" / "paper_draft.md").exists()
        assert "# My Paper" in (out / "02-writing" / "artifacts" / "paper_draft.md").read_text()

    def test_save_writes_rq_brief(self, tmp_path):
        r = PipelineResult({"topic": "AI", "rq_brief": "Research question brief"})
        out = r.save(tmp_path / "output")
        assert (out / "01-research" / "artifacts" / "rq_brief.md").exists()

    def test_save_writes_bibliography(self, tmp_path):
        r = PipelineResult({"topic": "AI", "bibliography": "1. Smith (2024)"})
        out = r.save(tmp_path / "output")
        assert (out / "01-research" / "artifacts" / "bibliography.md").exists()

    def test_save_writes_synthesis(self, tmp_path):
        r = PipelineResult({"topic": "AI", "synthesis": "Key themes"})
        out = r.save(tmp_path / "output")
        assert (out / "01-research" / "artifacts" / "synthesis.md").exists()

    def test_save_skips_empty_text_artifact(self, tmp_path):
        r = PipelineResult({"topic": "AI"})
        out = r.save(tmp_path / "output")
        assert not (out / "02-writing" / "artifacts" / "paper_draft.md").exists()
        assert not (out / "01-research" / "artifacts" / "rq_brief.md").exists()

    def test_save_json_review_report(self, tmp_path):
        report = {"score": 8, "decision": "Accept"}
        r = PipelineResult({"topic": "AI", "review_report": report})
        out = r.save(tmp_path / "output")
        assert (out / "04-review" / "artifacts" / "review_report.json").exists()
        data = json.loads((out / "04-review" / "artifacts" / "review_report.json").read_text())
        assert data["score"] == 8

    def test_save_json_integrity_report(self, tmp_path):
        report = {"verdict": "PASS", "issues": []}
        r = PipelineResult({"topic": "AI", "integrity_report": report})
        out = r.save(tmp_path / "output")
        assert (out / "03-integrity" / "artifacts" / "integrity_report.json").exists()
        data = json.loads((out / "03-integrity" / "artifacts" / "integrity_report.json").read_text())
        assert data["verdict"] == "PASS"

    def test_save_blocks_sensitive_paths(self, tmp_path):
        """Verify that save() rejects known sensitive system paths."""
        from unittest.mock import patch

        r = PipelineResult({"topic": "AI"})
        # Patch Path.resolve to return a path starting with /etc
        # (macOS resolves /etc -> /private/etc, so we mock to test the guard)
        for prefix in ("/etc", "/usr", "/bin", "/var", "/proc"):
            fake_path = f"{prefix}/pipeline_output"
            with (
                patch("academic_pipeline.sdk.result.Path.resolve", return_value=type(tmp_path)(fake_path)),
                pytest.raises(ValueError, match="sensitive"),
            ):
                r.save(fake_path)

    def test_save_returns_resolved_path(self, tmp_path):
        r = PipelineResult({"topic": "AI"})
        out = r.save(tmp_path / "output")
        assert out.is_absolute()

    def test_save_idempotent(self, tmp_path):
        r = PipelineResult({"topic": "AI", "paper_draft": {"title": "Test", "content": "Draft"}})
        out1 = r.save(tmp_path / "output")
        out2 = r.save(tmp_path / "output")
        assert out1 == out2


class TestPipelineResultProperties:
    """Tests for property accessors on PipelineResult."""

    def test_paper_draft_returns_dict(self):
        r = PipelineResult({"paper_draft": {"title": "Test", "content": "# Draft Content"}})
        assert r.paper_draft == {"title": "Test", "content": "# Draft Content"}

    def test_paper_draft_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.paper_draft is None

    def test_research_question_returns_rq_brief(self):
        r = PipelineResult({"rq_brief": "What is the impact of X on Y?"})
        assert r.research_question == "What is the impact of X on Y?"

    def test_research_question_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.research_question is None

    def test_bibliography_returns_value(self):
        r = PipelineResult({"bibliography": "1. Smith (2024). Title."})
        assert r.bibliography == "1. Smith (2024). Title."

    def test_bibliography_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.bibliography is None

    def test_synthesis_returns_value(self):
        r = PipelineResult({"synthesis": "Key themes identified."})
        assert r.synthesis == "Key themes identified."

    def test_synthesis_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.synthesis is None

    def test_review_report_returns_dict(self):
        report = {"score": 7, "decision": "Minor Revision"}
        r = PipelineResult({"review_report": report})
        assert r.review_report == report

    def test_review_report_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.review_report is None

    def test_integrity_report_returns_dict(self):
        report = {"verdict": "PASS", "issues": []}
        r = PipelineResult({"integrity_report": report})
        assert r.integrity_report == report

    def test_integrity_report_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.integrity_report is None

    def test_revision_roadmap_returns_value(self):
        r = PipelineResult({"revision_roadmap": "Step 1: Revise intro"})
        assert r.revision_roadmap == "Step 1: Revise intro"

    def test_revision_roadmap_returns_none_when_missing(self):
        r = PipelineResult({})
        assert r.revision_roadmap is None

    def test_status_returns_pipeline_status(self):
        r = PipelineResult({"pipeline_status": "completed"})
        assert r.status == "completed"

    def test_status_defaults_to_unknown(self):
        r = PipelineResult({})
        assert r.status == "unknown"

    def test_error_returns_error_message(self):
        r = PipelineResult({"error": "Something went wrong"})
        assert r.error == "Something went wrong"

    def test_error_returns_none_when_no_error(self):
        r = PipelineResult({})
        assert r.error is None

    def test_raw_returns_full_state(self):
        state = {"topic": "AI", "pipeline_status": "running", "extra": 42}
        r = PipelineResult(state)
        assert r.raw is state

    def test_paper_draft_returns_dict_value(self):
        draft = {"sections": ["intro", "body"]}
        r = PipelineResult({"paper_draft": draft})
        assert r.paper_draft == draft

    def test_research_question_returns_dict_value(self):
        rq = {"question": "What?", "sub_questions": ["Why?", "How?"]}
        r = PipelineResult({"rq_brief": rq})
        assert r.research_question == rq


class TestPipelineResultRepr:
    """Tests for __repr__ on PipelineResult."""

    def test_repr_with_status_and_topic(self):
        r = PipelineResult({"pipeline_status": "completed", "topic": "AI Safety"})
        result = repr(r)
        assert "PipelineResult" in result
        assert "completed" in result
        assert "AI Safety" in result

    def test_repr_defaults(self):
        r = PipelineResult({})
        result = repr(r)
        assert "unknown" in result
        assert "N/A" in result

    def test_repr_format(self):
        r = PipelineResult({"pipeline_status": "failed", "topic": "NLP"})
        assert repr(r) == "PipelineResult(status='failed', topic='NLP')"


# ---------------------------------------------------------------------------
# TDD: PipelineResult.save() artifact tests
# ---------------------------------------------------------------------------


def test_save_creates_output_directory(tmp_path: Path):
    result = PipelineResult(
        {
            "topic": "AI ethics",
            "pipeline_status": "completed",
            "paper_draft": {"title": "My Paper", "content": "# My Paper\n\nThis is the draft."},
        }
    )
    result.save(tmp_path / "run1")
    assert (tmp_path / "run1").is_dir()


def test_save_writes_paper_draft_as_markdown(tmp_path: Path):
    result = PipelineResult(
        {
            "topic": "AI ethics",
            "paper_draft": {"title": "Test", "content": "# Introduction\n\nContent here."},
        }
    )
    result.save(tmp_path / "out")
    paper = (tmp_path / "out" / "02-writing" / "artifacts" / "paper_draft.md").read_text()
    assert "# Introduction" in paper


def test_save_writes_research_outputs(tmp_path: Path):
    result = PipelineResult(
        {
            "topic": "AI",
            "rq_brief": "Research question brief content",
            "bibliography": "1. Smith (2024)...",
            "synthesis": "Key findings...",
        }
    )
    result.save(tmp_path / "out")
    assert (tmp_path / "out" / "01-research" / "artifacts" / "rq_brief.md").read_text() == "Research question brief content"
    assert (tmp_path / "out" / "01-research" / "artifacts" / "bibliography.md").exists()
    assert (tmp_path / "out" / "01-research" / "artifacts" / "synthesis.md").exists()


def test_save_writes_json_for_dict_artifacts(tmp_path: Path):
    result = PipelineResult(
        {
            "topic": "AI",
            "review_report": {"editorial_decision": "Accept", "score": 85},
            "integrity_report": {"verdict": "PASS"},
        }
    )
    result.save(tmp_path / "out")
    review = json.loads((tmp_path / "out" / "04-review" / "artifacts" / "review_report.json").read_text())
    assert review["editorial_decision"] == "Accept"
    integrity = json.loads((tmp_path / "out" / "03-integrity" / "artifacts" / "integrity_report.json").read_text())
    assert integrity["verdict"] == "PASS"


def test_save_skips_missing_artifacts(tmp_path: Path):
    result = PipelineResult({"topic": "AI"})
    result.save(tmp_path / "out")
    assert (tmp_path / "out").is_dir()
    assert not (tmp_path / "out" / "02-writing" / "artifacts" / "paper_draft.md").exists()


def test_save_returns_output_path(tmp_path: Path):
    result = PipelineResult({"topic": "AI"})
    path = result.save(tmp_path / "out")
    assert path == tmp_path / "out"
