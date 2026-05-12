"""High-level Pipeline class for programmatic use.

Wraps the PydanticAI pipeline graph with a simple async interface for
running the full research pipeline end-to-end.
Supports crash-recovery resume and human-in-the-loop checkpoints.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING

import pydantic

from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.persistence import SqliteStatePersistence
from academic_pipeline.pipeline.state import PipelineState
from academic_pipeline.recovery.heartbeat import Heartbeat
from academic_pipeline.recovery.process_state import ProcessLock
from academic_pipeline.runtime.dashboard import (
    DashboardDebouncer,
    RunState,
    apply_event,
    render,
)
from academic_pipeline.runtime.events import EventLogger
from academic_pipeline.sdk.result import PipelineResult


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Mapping

    from academic_pipeline.models.writing import PaperConfig
    from academic_pipeline.sdk.events import PipelineEvent


logger = logging.getLogger(__name__)


class _NullCM(AbstractContextManager["_NullCM"]):
    """Null context manager for code paths that don't need lock/heartbeat."""

    def __enter__(self) -> _NullCM:
        """Return self; no resources acquired."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Release nothing; tolerates any exception flow."""


class Pipeline:
    """Entry point for running the PydanticAI academic research pipeline.

    Supports crash-recovery and human-in-the-loop checkpoints. Set interactive=True for HITL prompts, False to
    auto-continue.
    """

    def __init__(
        self,
        topic: str,
        *,
        thread_id: str | None = None,
        interactive: bool = True,
        revision_instructions: str = "",
        persistence_dir: Path | None = None,
        use_dbos: bool = False,
        paper_config: PaperConfig | None = None,
    ) -> None:
        """Initialize the pipeline."""
        self.topic = topic
        self._use_dbos = use_dbos
        if thread_id:
            self.thread_id = thread_id
        else:
            from datetime import datetime

            self.thread_id = f"run-{datetime.now().strftime('%m%d-%H%M')}_{uuid.uuid4().hex[:4]}"
        self.interactive = interactive
        self._deps = PipelineDeps.create()
        if interactive:
            self._deps.hitl_handler = self._interactive_hitl_handler
        self._state = PipelineState(topic=self.topic, run_id=self.thread_id)
        if revision_instructions:
            self._state.revision_instructions = revision_instructions
        if paper_config is not None:
            self._state.paper_config = paper_config
        self._persistence_dir = persistence_dir or Path(".pipeline_runs")
        self._deps.persistence_dir = self._persistence_dir
        self._persistence = SqliteStatePersistence(
            db_path=self._persistence_dir / "pipeline.sqlite",
            run_id=self.thread_id,
        )
        self._state_adapter = pydantic.TypeAdapter(PipelineState)
        self._event_logger: EventLogger | None = None
        self._last_stage: str = ""
        self._last_node_t: float = 0.0
        self._run_state: RunState = RunState.empty()
        self._output_dir: str | None = None
        self._observers: list[Callable[[Mapping[str, object]], None]] = []
        # Cap dashboard.txt snapshot writes at 4 Hz (PRD §6.8.T4).
        self._dashboard_debouncer = DashboardDebouncer(min_interval_s=0.25)

    def observe(self, callback: Callable[[Mapping[str, object]], None]) -> Callable[[], None]:
        """Subscribe to pipeline event emissions.

        The callback receives the same dict that is appended to events.jsonl
        (keys: ``type``, ``ts``, plus event-specific fields). Cleaner than
        tailing events.jsonl from Python — PRD §6.12.T2.

        Returns a zero-arg cancel function. Invoking it removes this observer
        from future emissions; calling it more than once is a no-op.

        Observer exceptions are logged and swallowed: a misbehaving callback
        cannot crash the pipeline or starve other observers.
        """
        self._observers.append(callback)

        def cancel() -> None:
            import contextlib

            with contextlib.suppress(ValueError):
                self._observers.remove(callback)

        return cancel

    @property
    def state(self) -> PipelineState:
        """Read-only access to current pipeline state."""
        return self._state

    def _can_resume(self) -> bool:
        """Check if a previous run exists that can be resumed."""
        return self._persistence._can_resume_sync()

    def _reset_crashed_snapshots(self) -> None:
        """Reset any 'running' or 'error' snapshots to 'created' for re-execution."""
        self._persistence._reset_crashed_sync()
        logger.info("Reset crashed node(s) to 'created' for resume")

    def _save_state(self) -> None:
        """Persist PipelineState to SQLite so subsequent phases can resume."""
        self._persistence_dir.mkdir(parents=True, exist_ok=True)
        data = self._state_adapter.dump_json(self._state, indent=2).decode()  # pyright: ignore[reportArgumentType]
        self._persistence._save_pipeline_state_sync(self.thread_id, data)
        logger.info("Pipeline state saved to SQLite (run_id=%s)", self.thread_id)

    @staticmethod
    def _interactive_hitl_handler(message: str, node_name: str) -> str:
        """Prompt the user for input at a HITL checkpoint."""
        print(f"\n{'=' * 60}")
        print(f"CHECKPOINT: {node_name}")
        print(f"{'=' * 60}")
        print(message)
        print(f"{'=' * 60}")
        return input("Your feedback (or 'continue' to proceed): ").strip() or "continue"

    def _wrap_agents_with_dbos(self) -> None:
        """Wrap all agent registries with DBOSAgent for durable execution.

        Only wraps if DBOS was launched (use_dbos=True). Safe to call multiple times — skips if already wrapped.
        """
        if not self._use_dbos:
            return
        try:
            from pydantic_ai.durable_exec.dbos import DBOSAgent

            from academic_pipeline.integrity.agents import agents as integrity_agents
            from academic_pipeline.research.agents import agents as research_agents
            from academic_pipeline.review.agents import agents as review_agents
            from academic_pipeline.writing.agents import agents as writing_agents

            for registry in (research_agents, writing_agents, review_agents, integrity_agents):
                for name, agent in list(registry.items()):
                    if not isinstance(agent, DBOSAgent):
                        registry[name] = DBOSAgent(agent, name=name)  # type: ignore[assignment]
        except Exception:
            pass

    @staticmethod
    def _log_node_progress(node: object, start_time: float) -> None:
        elapsed = time.monotonic() - start_time
        node_name = type(node).__name__
        print(f"  [{elapsed:6.0f}s] {node_name}", file=sys.stderr, flush=True)

    def _run_output_dir(self, output_dir: str | None) -> str | None:
        """Return the run-specific output directory: output_dir/<run_id>/."""
        if not output_dir:
            return None
        from pathlib import Path

        run_dir = Path(output_dir) / self.thread_id
        # Symlink output/latest → output/<run_id> for convenience
        latest = Path(output_dir) / "latest"
        latest.unlink(missing_ok=True)
        import contextlib

        with contextlib.suppress(OSError):
            latest.symlink_to(self.thread_id)
        return str(run_dir)

    async def _emit_and_apply(self, event_type: str, **fields: object) -> None:
        """Emit an event to disk AND apply to in-memory RunState in one shot.

        Centralizes emit + apply + dashboard.txt re-render so callers do not
        need to repeat the three-step ritual. Captures ts once and passes it
        to both the disk emit and the in-memory apply so the two stay byte-equal.
        """
        if not self._event_logger:
            return
        import time as _time

        ts = _time.time()
        fields_with_ts = {"ts": ts, **fields}
        record = {"type": event_type, **fields_with_ts}
        await self._event_logger.emit(event_type, **fields_with_ts)
        self._run_state = apply_event(self._run_state, record)
        # PRD §6.12.T2 — fan out to programmatic observers. Isolated so a
        # buggy callback cannot crash the pipeline or starve siblings.
        for cb in list(self._observers):
            try:
                cb(record)
            except Exception:
                logger.exception("Pipeline.observe callback raised; continuing")
        if self._output_dir and self._dashboard_debouncer.acquire(now=ts):
            try:
                from rich.console import Console

                _console = Console(width=120, record=True)
                _console.print(render(self._run_state))
                (Path(self._output_dir) / "dashboard.txt").write_text(_console.export_text())
            except Exception:
                pass

    async def _save_intermediate(self, node: object, output_dir: str | None) -> None:
        """Save state and artifacts after each pipeline node completes.

        Emits stage_change (if the current stage advanced since the last save)
        and node_complete (scope=outer) events. Mirrors session timestamps
        into state so they survive the per-iteration ``self._state =
        graph_run.state`` reassignment that happens inside ``run_stream``.
        """
        import time as _time

        node_name_for_event = type(node).__name__
        now = _time.monotonic()
        duration_s = max(0.0, now - self._last_node_t) if self._last_node_t else 0.0
        self._last_node_t = now

        current_stage_str = str(self._state.current_stage) if self._state.current_stage else ""

        if self._event_logger:
            if current_stage_str and current_stage_str != self._last_stage:
                await self._emit_and_apply(
                    "stage_change",
                    stage=current_stage_str,
                    previous=self._last_stage or None,
                )
                self._last_stage = current_stage_str
            await self._emit_and_apply(
                "node_complete",
                stage=current_stage_str,
                node=node_name_for_event,
                scope="outer",
                duration_s=duration_s,
            )

        # Mirror session timestamps from instance attributes into state so they
        # survive the per-iteration self._state = graph_run.state reassignment.
        if hasattr(self, "_session_start_time"):
            meta = self._state.stages.setdefault("_meta", {})
            meta["session_start_time"] = self._session_start_time
            if "start_time" not in meta:
                meta["start_time"] = self._session_start_time

        self._save_state()
        run_dir = self._run_output_dir(output_dir)
        if run_dir:
            try:
                result = self._result()
                result.save(run_dir)
                print(f"  [saved] {run_dir}/", file=sys.stderr, flush=True)
            except Exception as e:
                logger.warning("Intermediate save failed after %s: %s", type(node).__name__, e)

    async def run_stream(self, output_dir: str | None = None) -> AsyncGenerator[PipelineEvent, None]:
        """Run the pipeline, yielding events as nodes execute."""
        from academic_pipeline.pipeline.graph import build_pipeline_graph
        from academic_pipeline.pipeline.nodes import IntakeNode
        from academic_pipeline.sdk.events import EventType, PipelineEvent

        run_dir: str | None = None
        if output_dir:
            from academic_pipeline.runtime.trace_logger import TraceLogger

            run_dir = self._run_output_dir(output_dir)
            if run_dir:
                self._deps.trace_logger = TraceLogger(Path(run_dir))
                self._event_logger = EventLogger(Path(run_dir))
                self._output_dir = run_dir
                self._deps._pipeline_ref = self  # type: ignore[attr-defined]

        # Compose PID lock + heartbeat as nested context managers so cleanup
        # is guaranteed on every exit path.
        if run_dir is None:
            heartbeat_cm: object = _NullCM()
            lock_cm: object = _NullCM()
        else:
            heartbeat_cm = Heartbeat(Path(run_dir) / "heartbeat.txt")
            lock_cm = ProcessLock(self._persistence_dir, self.thread_id)

        with lock_cm, heartbeat_cm:
            # Track session start (resets on every Pipeline.run() call) separate
            # from total start_time (set once on first run, persists across resumes).
            # Stored on self because self._state is replaced by graph_run.state
            # inside the iteration loop on resume — instance attributes survive.
            # _save_intermediate mirrors these into state on every save so the
            # dashboard sees them.
            self._session_start_time = time.time()
            self._last_node_t = time.monotonic()
            meta = self._state.stages.setdefault("_meta", {})
            meta["session_start_time"] = self._session_start_time
            if "start_time" not in meta:
                meta["start_time"] = self._session_start_time

            self._wrap_agents_with_dbos()
            t0 = time.monotonic()
            prev_stage = str(self._state.current_stage) if self._state.current_stage else ""
            prev_msg_count = len(self._state.messages)

            if self._event_logger:
                await self._emit_and_apply(
                    "pipeline_start",
                    run_id=self.thread_id,
                    topic=self.topic,
                    resumed=self._can_resume(),
                )

            try:
                graph = build_pipeline_graph()
                if self._can_resume():
                    self._reset_crashed_snapshots()
                    graph_ctx = graph.iter_from_persistence(
                        self._persistence,
                        deps=self._deps,
                    )
                else:
                    graph_ctx = graph.iter(
                        IntakeNode(),
                        state=self._state,
                        deps=self._deps,
                        persistence=self._persistence,
                    )

                async with graph_ctx as graph_run:  # pyright: ignore[reportArgumentType]
                    async for node in graph_run:
                        node_name = type(node).__name__
                        elapsed = time.monotonic() - t0
                        self._state = graph_run.state  # pyright: ignore[reportAttributeAccessIssue]

                        # Detect stage change
                        current_stage = str(self._state.current_stage) if self._state.current_stage else ""
                        if current_stage and current_stage != prev_stage:
                            yield PipelineEvent(
                                type=EventType.STAGE_CHANGE, data={"stage": current_stage, "status": "in_progress"}
                            )
                            prev_stage = current_stage

                        # Emit node_complete
                        yield PipelineEvent(
                            type=EventType.NODE_COMPLETE, data={"node": node_name, "elapsed_s": round(elapsed, 1)}
                        )

                        # Emit new messages
                        current_msg_count = len(self._state.messages)
                        if current_msg_count > prev_msg_count:
                            for msg in self._state.messages[prev_msg_count:]:
                                yield PipelineEvent(
                                    type=EventType.MESSAGE,
                                    data={"role": msg.get("role", ""), "content": msg.get("content", "")},
                                )
                            prev_msg_count = current_msg_count

                        # Save intermediate state + artifacts
                        await self._save_intermediate(node, output_dir)
                        self._log_node_progress(node, t0)

                self._save_state()
                if self._event_logger:
                    await self._emit_and_apply("pipeline_complete")
                yield PipelineEvent(type=EventType.COMPLETE, data={"status": "completed"})

            except Exception as exc:
                if self._event_logger:
                    await self._emit_and_apply("pipeline_error", error=str(exc))
                yield PipelineEvent(type=EventType.ERROR, data={"error": str(exc)})
                raise

    async def run(self, output_dir: str | None = None) -> PipelineResult:
        """Run the full pipeline, resuming from last checkpoint if available."""
        async for _event in self.run_stream(output_dir=output_dir):
            pass
        return self._result()

    def _result(self) -> PipelineResult:
        """Wrap current state into a PipelineResult."""
        from dataclasses import asdict

        return PipelineResult(asdict(self._state))  # pyright: ignore[reportArgumentType]
