"""Tests for SqliteStatePersistence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pydantic_graph import BaseNode, End, Graph, GraphRunContext
from pydantic_graph.persistence import EndSnapshot, NodeSnapshot

from academic_pipeline.persistence import SqliteStatePersistence


if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class TestState:
    counter: int = 0


@dataclass
class IncrementNode(BaseNode[TestState, None, int]):
    async def run(self, ctx: GraphRunContext[TestState, None]) -> IncrementNode | End[int]:
        ctx.state.counter += 1
        if ctx.state.counter >= 3:
            return End(ctx.state.counter)
        return IncrementNode()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


@pytest.fixture()
def persistence(db_path: Path) -> SqliteStatePersistence[TestState, int]:
    p = SqliteStatePersistence[TestState, int](db_path=db_path, run_id="test-run")
    graph = Graph(nodes=[IncrementNode])
    p.set_graph_types(graph)
    return p


class TestSnapshotNode:
    def test_snapshot_node_stores_and_loads(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Snapshot_node adds a NodeSnapshot; load_all returns it with status 'created'."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snapshots = await persistence.load_all()
            assert len(snapshots) == 1
            snap = snapshots[0]
            assert isinstance(snap, NodeSnapshot)
            assert snap.status == "created"
            assert snap.state.counter == 0

        asyncio.run(_test())


class TestSnapshotEnd:
    def test_snapshot_end_stores_and_loads(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Snapshot_end adds an EndSnapshot; load_all returns it."""
        state = TestState(counter=3)
        end = End(3)

        async def _test() -> None:
            await persistence.snapshot_end(state, end)
            snapshots = await persistence.load_all()
            assert len(snapshots) == 1
            snap = snapshots[0]
            assert isinstance(snap, EndSnapshot)
            assert snap.state.counter == 3
            assert snap.result.data == 3

        asyncio.run(_test())


class TestLoadNext:
    def test_load_next_returns_created_snapshot(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Load_next returns the first 'created' snapshot and sets status to 'pending'."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snap = await persistence.load_next()
            assert snap is not None
            assert isinstance(snap, NodeSnapshot)
            assert snap.status == "pending"

        asyncio.run(_test())

    def test_load_next_returns_none_when_empty(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Load_next returns None when no snapshots exist."""

        async def _test() -> None:
            snap = await persistence.load_next()
            assert snap is None

        asyncio.run(_test())


class TestSnapshotNodeIfNew:
    def test_skips_duplicate_snapshot_id(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Snapshot_node_if_new does not add a duplicate when snapshot_id already exists."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snapshots = await persistence.load_all()
            assert len(snapshots) == 1
            existing_id = snapshots[0].id

            # Attempt to add again with the same snapshot_id
            await persistence.snapshot_node_if_new(existing_id, state, node)
            snapshots_after = await persistence.load_all()
            assert len(snapshots_after) == 1

        asyncio.run(_test())


class TestRecordRun:
    def test_record_run_sets_status_success(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Record_run sets status to 'success' and duration is not None on normal exit."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snapshots = await persistence.load_all()
            snap_id = snapshots[0].id

            async with persistence.record_run(snap_id):
                pass  # simulate successful run

            snapshots_after = await persistence.load_all()
            snap = snapshots_after[0]
            assert isinstance(snap, NodeSnapshot)
            assert snap.status == "success"
            assert snap.duration is not None

        asyncio.run(_test())

    def test_record_run_sets_status_error_on_exception(
        self, persistence: SqliteStatePersistence[TestState, int]
    ) -> None:
        """Record_run sets status to 'error' when an exception is raised inside the context."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snapshots = await persistence.load_all()
            snap_id = snapshots[0].id

            with pytest.raises(ValueError, match="boom"):
                async with persistence.record_run(snap_id):
                    raise ValueError("boom")

            snapshots_after = await persistence.load_all()
            snap = snapshots_after[0]
            assert isinstance(snap, NodeSnapshot)
            assert snap.status == "error"

        asyncio.run(_test())


class TestPipelineState:
    def test_save_and_load_pipeline_state(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Save_pipeline_state stores JSON; load_pipeline_state retrieves it."""
        from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

        payload = f'{{"topic": "test", "_schema_version": {PIPELINE_STATE_SCHEMA_VERSION}}}'

        async def _test() -> None:
            await persistence.save_pipeline_state("run-1", payload)
            loaded = await persistence.load_pipeline_state("run-1")
            assert loaded == payload

        asyncio.run(_test())

    def test_load_missing_returns_none(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Load_pipeline_state returns None for a nonexistent run_id."""

        async def _test() -> None:
            loaded = await persistence.load_pipeline_state("nonexistent")
            assert loaded is None

        asyncio.run(_test())

    def test_upsert_overwrites(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Saving twice with the same run_id overwrites the previous value."""
        from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

        v1 = f'{{"v": 1, "_schema_version": {PIPELINE_STATE_SCHEMA_VERSION}}}'
        v2 = f'{{"v": 2, "_schema_version": {PIPELINE_STATE_SCHEMA_VERSION}}}'

        async def _test() -> None:
            await persistence.save_pipeline_state("run-1", v1)
            await persistence.save_pipeline_state("run-1", v2)
            loaded = await persistence.load_pipeline_state("run-1")
            assert loaded == v2

        asyncio.run(_test())


class TestResetCrashedSnapshots:
    def test_resets_running_and_error_to_created(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Reset_crashed_snapshots resets 'error' status back to 'created'."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            snapshots = await persistence.load_all()
            snap_id = snapshots[0].id

            # Force the snapshot into 'error' status via record_run
            with pytest.raises(ValueError, match="crash"):
                async with persistence.record_run(snap_id):
                    raise ValueError("crash")

            # Verify it's in error state
            snapshots_mid = await persistence.load_all()
            assert isinstance(snapshots_mid[0], NodeSnapshot)
            assert snapshots_mid[0].status == "error"

            # Reset crashed snapshots
            await persistence.reset_crashed_snapshots()

            # Verify it's back to 'created'
            snapshots_after = await persistence.load_all()
            assert isinstance(snapshots_after[0], NodeSnapshot)
            assert snapshots_after[0].status == "created"

        asyncio.run(_test())


class TestCanResume:
    def test_can_resume_false_when_empty(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Can_resume returns False when no snapshots exist."""

        async def _test() -> None:
            result = await persistence.can_resume()
            assert result is False

        asyncio.run(_test())

    def test_can_resume_true_after_snapshot(self, persistence: SqliteStatePersistence[TestState, int]) -> None:
        """Can_resume returns True after a snapshot is added."""
        state = TestState(counter=0)
        node = IncrementNode()

        async def _test() -> None:
            await persistence.snapshot_node(state, node)
            result = await persistence.can_resume()
            assert result is True

        asyncio.run(_test())


# ============================================================================
# PRD §6.9.T6 — Persistence test inventory
# ============================================================================
#
# The 6 tests called for by PRD §6.9.T6 are split across three modules so
# each lives next to the code it exercises (cleaner than one mega-file). The
# inventory below is the canonical pointer; do not move tests back without
# updating PRD §16.
#
# Schema-version rejection (§6.9.T1):
#   tests/unit/test_persistence_schema_version.py
#     - test_pipeline_state_has_schema_version_field
#     - test_load_rejects_missing_schema_version_with_prs001
#     - test_load_rejects_mismatched_schema_version_with_prs001
#     - test_load_returns_state_for_matching_schema_version
#     - test_load_returns_none_when_run_id_absent
#
# Per-agent cache isolation (§6.9.T2):
#   tests/unit/experiment/test_agent_cache.py
#     - test_for_agent_classmethod_returns_cache_at_per_thread_dir
#     - test_for_agent_isolates_caches_across_agents_within_same_thread
#     - test_for_agent_isolates_caches_across_threads_for_same_agent
#
# Cleanup script dry-run + confirm + purge + idempotency (§6.9.T5):
#   tests/unit/tools/test_cleanup_state.py
#     - test_dry_run_reports_but_moves_nothing
#     - test_confirm_archives_incompatible_files_by_default
#     - test_purge_actually_deletes_when_confirmed
#     - test_skips_files_already_in_archive
#     - test_idempotent_no_op_on_already_clean_dir
#     - test_handles_missing_runs_dir_gracefully
#     - test_cli_subcommand_exists_and_runs_dry_by_default
#     - test_cli_subcommand_confirm_archives
#
# Two cache-resume tests below are placeholders deferred to Phase 4 — they
# require the dialogue helper (§6.3.T9) and config_writer wiring (§6.9.T4)
# which both land in Phase 4. PRD §6.9.T6 explicitly notes the deferral.


@pytest.mark.skip(reason="awaits §6.3.T9 + §6.9.T3 dialogue helper wiring (Phase 4)")
def test_dialogue_cache_resume_round_trips_message_history() -> None:
    """draft_writer↔reviewer dialogue cache survives an interrupt + resume.

    When §6.9.T3 lands, AgentMessageCache.for_agent('draft_writer_dialogue',
    thread_id) will be wired into the dialogue helper. This test will assert
    that a partial dialogue can be loaded back via message_history= on the
    next agent.run() call so the conversation continues mid-turn instead of
    restarting.
    """
    raise NotImplementedError("waiting on §6.3.T9 + §6.9.T3")


@pytest.mark.skip(reason="awaits §6.9.T4 config_writer cache wiring (Phase 4)")
def test_config_writer_cache_resume_iterates_on_dagster_failure_feedback() -> None:
    """config_writer cache survives a Dagster failure + resume.

    When §6.9.T4 lands, AgentMessageCache.for_agent('config_writer',
    thread_id) will be wired into the experiment subgraph so config_writer
    can iterate on Dagster failure feedback without losing context across
    crash/resume boundaries. This test will assert the message_history=
    round-trips correctly.
    """
    raise NotImplementedError("waiting on §6.9.T4")
