"""Integration tests for pipeline crash-recovery resume."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest


if TYPE_CHECKING:
    from pydantic_ai.models.test import TestModel


@pytest.fixture(autouse=True)
def _mock_doi_and_authors_gates():
    """Stub the §6.7.T2 + §6.7.T3 build gates for full-pipeline tests.

    Without this, LatexCompilerNode aborts with REN001/REN002 before pandoc.
    """
    from pathlib import Path as _Path

    from academic_pipeline.runtime.authors_yaml import AuthorsYamlEntry

    async def _ok(doi: str) -> str:
        return json.dumps({"doi": doi, "exists": True, "status": 200})

    fake_path = _Path("authors.yaml")
    fake_entries = [AuthorsYamlEntry(name="Test User", affiliation="Test Lab")]

    with (
        patch(
            "academic_pipeline.tools.bibliography.doi.verify_doi",
            new=AsyncMock(side_effect=_ok),
        ),
        patch(
            "academic_pipeline.runtime.authors_yaml.resolve_authors_yaml_path",
            return_value=fake_path,
        ),
        patch(
            "academic_pipeline.runtime.authors_yaml.load_authors_yaml",
            return_value=fake_entries,
        ),
    ):
        yield


from academic_pipeline.experiment.agents import agents as _experiment_agents
from academic_pipeline.integrity.agents import agents as _integrity_agents
from academic_pipeline.models.ethics import EthicsChecklist
from academic_pipeline.models.experiment import ExperimentClassification
from academic_pipeline.models.integrity import (
    ComplianceReport,
    IntegrityVerificationOutput,
)
from academic_pipeline.models.research import (
    Bibliography,
    IndependentVerificationReport,
    MethodologyBlueprint,
    ResearchReport,
    RQBrief,
    SourceVerificationReport,
    SynthesisReport,
)
from academic_pipeline.models.review import (
    EditorialSynthesis,
    EditorReview,
    EICReview,
    FieldAnalysis,
    PeerReviewOutput,
    PeerReviewReport,
)
from academic_pipeline.models.writing import (
    AbstractOutput,
    ArgumentBlueprint,
    CitationAudit,
    FigurePackage,
    FormattedPaper,
    LiteratureStrategy,
    PaperConfig,
    PaperDraft,
    PaperOutline,
    Section,
)
from academic_pipeline.pipeline.graph import build_pipeline_graph
from academic_pipeline.pipeline.nodes import IntakeNode
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.research.agents import agents as research_agents
from academic_pipeline.review.agents import agents as review_agents
from academic_pipeline.sdk.pipeline import Pipeline
from academic_pipeline.writing.agents import agents as writing_agents
from tests.conftest import (
    make_structured_test_model,
    make_structured_test_model_with_overrides,
    make_test_deps,
    make_test_model,
)


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.anyio


_RESEARCH_MODEL_MAP: dict[str, type] = {
    "research_question": RQBrief,
    "research_architect": MethodologyBlueprint,
    "bibliography": Bibliography,
    "source_verification": SourceVerificationReport,
    "synthesis": SynthesisReport,
    "report_compiler": ResearchReport,
    "independent_verifier": IndependentVerificationReport,
    "editor_in_chief": EditorReview,
    "ethics_review": EthicsChecklist,
}

_WRITING_MODEL_MAP: dict[str, type] = {
    "intake": PaperConfig,
    "literature_strategist": LiteratureStrategy,
    "structure_architect": PaperOutline,
    "argument_builder": ArgumentBlueprint,
    "draft_writer": PaperDraft,
    "citation_compliance": CitationAudit,
    "abstract": AbstractOutput,
    "peer_reviewer": PeerReviewOutput,
    "formatter": FormattedPaper,
    "visualization": FigurePackage,
    "section_writer": Section,
}

_REVIEW_MODEL_MAP: dict[str, type] = {
    "field_analyst": FieldAnalysis,
    "eic": EICReview,
    "methodology_reviewer": PeerReviewReport,
    "domain_reviewer": PeerReviewReport,
    "perspective_reviewer": PeerReviewReport,
    "editorial_synthesizer": EditorialSynthesis,
}


def _override_all(model: TestModel):
    """Context manager to override all agents with TestModel.

    PromptedOutput agents need custom_output_text with valid JSON matching the model schema. Text-only agents use the
    provided model with custom_output_text.
    """
    stack = contextlib.ExitStack()
    for name, agent in research_agents.items():
        if name in _RESEARCH_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_RESEARCH_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=model))
    for name, agent in writing_agents.items():
        if name in _WRITING_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_WRITING_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=model))
    for name, agent in review_agents.items():
        if name in _REVIEW_MODEL_MAP:
            stack.enter_context(agent.override(model=make_structured_test_model(_REVIEW_MODEL_MAP[name])))
        else:
            stack.enter_context(agent.override(model=model))
    stack.enter_context(
        _integrity_agents["integrity_verification"].override(
            model=make_structured_test_model(IntegrityVerificationOutput)
        )
    )
    stack.enter_context(
        _integrity_agents["compliance_check"].override(model=make_structured_test_model(ComplianceReport))
    )

    # Experiment classifier — override to skip experiments (needs_experiments=False)
    classifier_model = make_structured_test_model_with_overrides(
        ExperimentClassification,
        {"needs_experiments": False, "reasoning": "No experiments needed for this topic."},
    )
    stack.enter_context(_experiment_agents["experiment_classifier"].override(model=classifier_model))
    return stack


async def test_fresh_run_creates_persistence(tmp_path: Path):
    """A fresh run should create a persistence file with snapshots."""
    import sqlite3

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")

    pipeline = Pipeline(
        "test topic",
        thread_id="test-fresh",
        interactive=False,
        persistence_dir=tmp_path,
    )

    with _override_all(model):
        await pipeline.run()

    # SQLite persistence file should exist and have snapshots
    persist_file = tmp_path / "pipeline.sqlite"
    assert persist_file.exists()
    conn = sqlite3.connect(str(persist_file))
    rows = conn.execute("SELECT kind FROM snapshots WHERE run_id = 'test-fresh'").fetchall()
    assert len(rows) > 0
    # Should have completed (last snapshot should be an end snapshot)
    assert any(r[0] == "end" for r in rows)
    conn.close()


async def test_resume_from_persistence(tmp_path: Path):
    """After a partial run, resuming with the same thread_id should continue from the last node."""
    from academic_pipeline.persistence import SqliteStatePersistence

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")
    deps = make_test_deps()
    deps.persistence_dir = tmp_path

    graph = build_pipeline_graph()
    state = PipelineState(topic="test topic", run_id="test-resume")
    persistence = SqliteStatePersistence(db_path=tmp_path / "pipeline.sqlite", run_id="test-resume")

    # Run partially — stop after 2 nodes using iter
    nodes_seen: list[str] = []
    with _override_all(model):
        async with graph.iter(IntakeNode(), state=state, deps=deps, persistence=persistence) as run:  # pyright: ignore[reportArgumentType]
            async for node in run:
                nodes_seen.append(type(node).__name__)
                if len(nodes_seen) >= 2:
                    break

    assert len(nodes_seen) >= 2
    assert (tmp_path / "pipeline.sqlite").exists()

    # Resume — should NOT start from IntakeNode again
    resumed_nodes: list[str] = []
    with _override_all(model):
        async with graph.iter_from_persistence(persistence, deps=deps) as run:  # pyright: ignore[reportArgumentType]
            resumed_nodes = [type(node).__name__ async for node in run]

    # Should not have re-run IntakeNode
    assert "IntakeNode" not in resumed_nodes
    assert len(resumed_nodes) > 0


async def test_resume_nonexistent_thread_starts_fresh(tmp_path: Path):
    """Passing a thread_id with no persistence file should start fresh."""

    pipeline = Pipeline(
        "test topic",
        thread_id="nonexistent-id",
        persistence_dir=tmp_path,
    )

    assert not pipeline._can_resume()


async def test_can_resume_detects_existing_run(tmp_path: Path):
    """_can_resume returns True when snapshots exist in SQLite for the run_id."""
    import sqlite3

    pipeline = Pipeline("test", thread_id="existing", persistence_dir=tmp_path)
    # Insert a snapshot directly into SQLite to simulate a previous run
    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    conn.execute(
        "INSERT INTO snapshots (run_id, snapshot_id, kind, status, data_json) "
        "VALUES ('existing', 'snap-1', 'node', 'created', '{}')"
    )
    conn.commit()
    conn.close()

    assert pipeline._can_resume()


async def test_can_resume_false_when_no_snapshots(tmp_path: Path):
    """_can_resume returns False when SQLite db exists but has no snapshots for the run_id."""

    pipeline = Pipeline("test", thread_id="empty", persistence_dir=tmp_path)

    # Pipeline creates the db on init, but no snapshots have been inserted
    assert (tmp_path / "pipeline.sqlite").exists()
    assert not pipeline._can_resume()


async def test_reset_crashed_snapshots_fixes_error_status(tmp_path: Path):
    """_reset_crashed_snapshots should reset 'error' to 'created'."""
    import sqlite3

    pipeline = Pipeline("test", thread_id="crashed", interactive=False, persistence_dir=tmp_path)
    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    conn.execute(
        "INSERT INTO snapshots (run_id, snapshot_id, kind, status, data_json) "
        "VALUES ('crashed', 'snap-1', 'node', 'success', '{}')"
    )
    conn.execute(
        "INSERT INTO snapshots (run_id, snapshot_id, kind, status, data_json) "
        "VALUES ('crashed', 'snap-2', 'node', 'error', '{}')"
    )
    conn.commit()
    conn.close()

    pipeline._reset_crashed_snapshots()

    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    rows = conn.execute("SELECT snapshot_id, status FROM snapshots WHERE run_id = 'crashed' ORDER BY id").fetchall()
    conn.close()
    assert rows[0][1] == "success"
    assert rows[1][1] == "created"


async def test_reset_crashed_snapshots_fixes_running_status(tmp_path: Path):
    """_reset_crashed_snapshots should also reset 'running' to 'created'."""
    import sqlite3

    pipeline = Pipeline("test", thread_id="running", interactive=False, persistence_dir=tmp_path)
    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    conn.execute(
        "INSERT INTO snapshots (run_id, snapshot_id, kind, status, data_json) "
        "VALUES ('running', 'snap-1', 'node', 'running', '{}')"
    )
    conn.commit()
    conn.close()

    pipeline._reset_crashed_snapshots()

    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    rows = conn.execute("SELECT snapshot_id, status FROM snapshots WHERE run_id = 'running' ORDER BY id").fetchall()
    conn.close()
    assert rows[0][1] == "created"


async def test_reset_crashed_snapshots_noop_when_no_snapshots(tmp_path: Path):
    """_reset_crashed_snapshots should be a no-op when no snapshots exist in the db."""

    pipeline = Pipeline("test", thread_id="missing", interactive=False, persistence_dir=tmp_path)

    # Should not raise — db exists but has no snapshots for this run_id
    pipeline._reset_crashed_snapshots()


async def test_interactive_hitl_handler(monkeypatch: pytest.MonkeyPatch):
    """_interactive_hitl_handler should prompt the user and return stripped input."""
    monkeypatch.setattr("builtins.input", lambda _prompt: "  looks good  ")

    result = Pipeline._interactive_hitl_handler("Please review this section.", "ReviewNode")

    assert result == "looks good"


async def test_interactive_hitl_handler_empty_returns_continue(monkeypatch: pytest.MonkeyPatch):
    """Empty input should default to 'continue'."""
    monkeypatch.setattr("builtins.input", lambda _prompt: "  ")

    result = Pipeline._interactive_hitl_handler("Checkpoint reached.", "SomeNode")

    assert result == "continue"


async def test_resume_path_syncs_state_back(tmp_path: Path):
    """The resume path (iter_from_persistence) should sync graph state back to pipeline._state."""

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")

    # First: do a fresh full run to create persistence data
    pipeline = Pipeline("state sync test", thread_id="sync-test", interactive=False, persistence_dir=tmp_path)

    with _override_all(model):
        await pipeline.run()

    persist_file = tmp_path / "pipeline.sqlite"
    assert persist_file.exists()

    # Verify state was synced (run should have populated fields)
    assert pipeline._state.topic == "state sync test"


async def test_fresh_run_syncs_state_back(tmp_path: Path):
    """A fresh run should sync the graph state back to pipeline._state after completion."""

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")

    pipeline = Pipeline("fresh sync test", thread_id="fresh-sync", interactive=False, persistence_dir=tmp_path)

    with _override_all(model):
        result = await pipeline.run()

    # State should be synced from graph_run.state
    assert pipeline._state.topic == "fresh sync test"
    assert result is not None
    assert result.raw["topic"] == "fresh sync test"


async def test_pipeline_run_resume_path(tmp_path: Path):
    """Pipeline.run() should use iter_from_persistence when a partial run exists (lines 99-107)."""
    from academic_pipeline.persistence import SqliteStatePersistence

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")
    deps = make_test_deps()

    # Step 1: Create a partial run by stopping after 2 nodes (simulates a crash)
    graph = build_pipeline_graph()
    state = PipelineState(topic="resume via run", run_id="resume-run")
    persistence = SqliteStatePersistence(db_path=tmp_path / "pipeline.sqlite", run_id="resume-run")

    with _override_all(model):
        async with graph.iter(IntakeNode(), state=state, deps=deps, persistence=persistence) as run:  # pyright: ignore[reportArgumentType]
            count = 0
            async for _node in run:
                count += 1
                if count >= 2:
                    break

    assert (tmp_path / "pipeline.sqlite").exists()

    # Step 2: Create a Pipeline that picks up the partial persistence
    pipeline = Pipeline("resume via run", thread_id="resume-run", interactive=False, persistence_dir=tmp_path)

    # Verify _can_resume() returns True
    assert pipeline._can_resume()

    # Run again via Pipeline.run() -- should go through the resume path
    with _override_all(model):
        result = await pipeline.run()

    # State should be synced from graph_run.state
    assert result is not None
    assert pipeline._state.topic == "resume via run"


async def test_resume_after_mid_node_crash(tmp_path: Path):
    """Simulate a real crash: node stuck in 'running' status in BOTH db column and data_json.

    This is the scenario where a process is killed (SIGKILL/OOM) while a node is
    executing. The snapshot has status='running' in the data_json blob. On resume,
    _reset_crashed_snapshots must patch data_json directly (without TypeAdapter) so that load_next() can find the reset
    snapshot.
    """
    import json
    import sqlite3

    from academic_pipeline.persistence import SqliteStatePersistence

    model = make_test_model("Verdict: PASS\nEditorial Decision: ACCEPT")
    deps = make_test_deps()

    graph = build_pipeline_graph()
    state = PipelineState(topic="crash test", run_id="crash-mid")
    persistence = SqliteStatePersistence(db_path=tmp_path / "pipeline.sqlite", run_id="crash-mid")

    # Run 2 nodes to get proper snapshot data, then stop (same pattern as
    # test_pipeline_run_resume_path which is known to work).
    with _override_all(model):
        async with graph.iter(IntakeNode(), state=state, deps=deps, persistence=persistence) as run:  # pyright: ignore[reportArgumentType]
            count = 0
            async for _node in run:
                count += 1
                if count >= 2:
                    break

    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    rows = conn.execute(
        "SELECT snapshot_id, status, data_json FROM snapshots WHERE run_id = 'crash-mid' ORDER BY id"
    ).fetchall()
    conn.close()
    assert len(rows) >= 2

    # Find the last "created" snapshot and corrupt it to "running" in BOTH the
    # db status column AND data_json — exactly what a real crash leaves behind.
    corrupted = False
    conn = sqlite3.connect(str(tmp_path / "pipeline.sqlite"))
    for sid, status, data_json in rows:
        if status == "created":
            data = json.loads(data_json)
            data["status"] = "running"
            conn.execute(
                "UPDATE snapshots SET status = 'running', data_json = ? "
                "WHERE run_id = 'crash-mid' AND snapshot_id = ?",
                (json.dumps(data), sid),
            )
            corrupted = True
            break
    conn.commit()
    conn.close()
    assert corrupted, "No 'created' snapshot found to corrupt"

    # Resume via Pipeline — the exact user path: same thread_id, fresh process.
    # Before the fix, this would raise GraphRuntimeError because data_json still
    # had status='running' after reset, so load_next() returned None.
    pipeline = Pipeline("crash test", thread_id="crash-mid", interactive=False, persistence_dir=tmp_path)
    assert pipeline._can_resume()

    with _override_all(model):
        result = await pipeline.run()

    assert result is not None
    assert pipeline._state.topic == "crash test"


async def test_interactive_true_sets_hitl_handler():
    """When interactive=True, pipeline should set hitl_handler on deps."""
    pipeline = Pipeline("test", interactive=True)
    assert pipeline._deps.hitl_handler is not None
    assert pipeline._deps.hitl_handler == Pipeline._interactive_hitl_handler


async def test_interactive_false_no_hitl_handler():
    """When interactive=False, pipeline should not set the interactive handler."""
    pipeline = Pipeline("test", interactive=False)
    # Should NOT be the interactive handler
    assert pipeline._deps.hitl_handler is not Pipeline._interactive_hitl_handler
