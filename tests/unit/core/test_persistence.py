"""Test Pipeline state persistence between phases."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from academic_pipeline.models.research import (
    FINERScores,
    RQBrief,
    Scope,
)
from academic_pipeline.sdk.pipeline import Pipeline


def _make_rq_brief() -> RQBrief:
    return RQBrief(
        research_question="Test RQ?",
        sub_questions=["SQ1?", "SQ2?"],
        finer_scores=FINERScores(feasible=4, interesting=4, novel=4, ethical=5, relevant=5),
        scope=Scope(
            in_scope=["a"],
            out_of_scope=["b"],
            domain="test",
            timeframe="2025",
            geography="global",
            population="all",
        ),
        methodology_type="mixed",
        theoretical_framework="Rogers DOI",
        keywords=["a", "b", "c", "d", "e"],
    )


class TestStatePersistence:
    def test_save_state_creates_db(self, tmp_path: Path) -> None:
        """_save_state should create the SQLite database and store state."""
        p = Pipeline("test topic", thread_id="test-save", interactive=False, persistence_dir=tmp_path)
        p._state.rq_brief = _make_rq_brief()
        p._save_state()

        db_file = tmp_path / "pipeline.sqlite"
        assert db_file.exists()

    def test_saved_state_readable_from_sqlite(self, tmp_path: Path) -> None:
        """State saved by Pipeline should be readable via SqliteStatePersistence."""
        import json

        from academic_pipeline.persistence import SqliteStatePersistence

        p = Pipeline("test topic", thread_id="test-read", interactive=False, persistence_dir=tmp_path)
        p._state.rq_brief = _make_rq_brief()
        p._save_state()

        persistence = SqliteStatePersistence(db_path=tmp_path / "pipeline.sqlite", run_id="test-read")
        state_json = persistence._load_pipeline_state_sync("test-read")
        assert state_json is not None
        data = json.loads(state_json)
        assert data["topic"] == "test topic"
        assert data["rq_brief"]["research_question"] == "Test RQ?"
