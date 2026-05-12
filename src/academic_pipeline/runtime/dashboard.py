"""Events-driven pipeline dashboard. Pure renderer over events.jsonl."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import reduce
from typing import TYPE_CHECKING, Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


logger = logging.getLogger(__name__)


class DashboardDebouncer:
    """Rate-limit dashboard.txt snapshot writes to ≤4 Hz (PRD §6.8.T4).

    Inline utility — NOT runtime/throttle.py per PRD AP84 (that module is
    the PydanticAI Hooks-based agent throttle, wrong API surface).
    """

    def __init__(self, min_interval_s: float = 0.25) -> None:
        """Set the minimum interval between snapshot writes (default 250ms = 4 Hz)."""
        self.min_interval_s = min_interval_s
        # Sentinel ensures the first acquire() is always allowed regardless
        # of the absolute `now` value (incl. now=0.0 in tests).
        self._last_write_ts: float = float("-inf")

    def acquire(self, now: float) -> bool:
        """Return True iff a snapshot write is allowed at `now`.

        Records the write timestamp on True. Blocked attempts do NOT reset
        the clock — otherwise rapid callers could indefinitely defer writes.
        """
        if now - self._last_write_ts >= self.min_interval_s:
            self._last_write_ts = now
            return True
        return False


class SchemaVersionMismatch(Exception):  # noqa: N818 — name fixed by PRD §17 (DSH001 SchemaVersionMismatch)
    """Raised when an events.jsonl schema_version major differs from the renderer's.

    Error code: DSH001 (PRD §17 + §6.8.T3). Pre-v2.5.0 events.jsonl files lack
    the marker entirely and are also rejected by this exception (PRD R21).
    """


def validate_schema_version(path: Path) -> None:
    """Verify `path` first line carries a matching-major schema_version marker.

    Raises ``SchemaVersionMismatch`` (DSH001) otherwise. The marker shape is
    ``{"event_type": "schema_version", "version": "X.Y.Z"}`` written as the
    first line by ``EventLogger.__init__``. Renderer compares only the major
    (``X``) — minor/patch differences are tolerated.
    """
    from academic_pipeline.runtime.events import SCHEMA_VERSION

    expected_major = SCHEMA_VERSION.split(".")[0]
    if not path.exists():
        msg = f"DSH001 SchemaVersionMismatch: events.jsonl not found at {path}"
        raise SchemaVersionMismatch(msg)
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    if not first_line:
        msg = f"DSH001 SchemaVersionMismatch: events.jsonl at {path} is empty"
        raise SchemaVersionMismatch(msg)
    try:
        marker = json.loads(first_line)
    except json.JSONDecodeError as exc:
        msg = f"DSH001 SchemaVersionMismatch: first line of {path} is not valid JSON: {exc}"
        raise SchemaVersionMismatch(msg) from exc
    if marker.get("event_type") != "schema_version":
        msg = (
            f"DSH001 SchemaVersionMismatch: first line of {path} lacks the schema_version "
            f"marker (likely a pre-v{SCHEMA_VERSION} file); upgrade or re-run the pipeline"
        )
        raise SchemaVersionMismatch(msg)
    version = marker.get("version", "")
    actual_major = str(version).split(".")[0]
    if actual_major != expected_major:
        msg = (
            f"DSH001 SchemaVersionMismatch: events.jsonl declares version {version!r} "
            f"(major {actual_major}); renderer expects major {expected_major} "
            f"(SCHEMA_VERSION={SCHEMA_VERSION})"
        )
        raise SchemaVersionMismatch(msg)


# Display order matches actual pipeline execution flow.
# This is the ONLY static topology list in the dashboard.
STAGE_DISPLAY_ORDER: tuple[str, ...] = (
    "research",
    "experiment",
    "write",
    "pre_integrity",
    "review",
    "final_integrity",
    "finalize",
    "summary",
)


@dataclass(frozen=True)
class NodeInfo:
    """One completed (or errored) node within a stage."""

    name: str
    scope: str  # "outer" | "subgraph"
    duration_s: float
    status: str  # "completed" | "error"
    error: str | None


@dataclass(frozen=True)
class StageInfo:
    """One pipeline stage with its completed nodes."""

    name: str
    nodes: tuple[NodeInfo, ...]
    started_at: float | None
    ended_at: float | None
    status: str  # "pending" | "running" | "completed" | "error"


@dataclass(frozen=True)
class WatchdogAction:
    """One watchdog action observed during a run."""

    action: str  # "killing" | "killed" | "resuming" | "resumed" | "aborted"
    ts: float
    pgid: int | None
    age_s: float | None
    strike: int | None
    reason: str | None
    killed_cleanly: bool | None


@dataclass(frozen=True)
class RecoveryEventInfo:
    """One generic recovery_event record (PRD §6.6.T2)."""

    layer: int
    action: str  # "kill" | "resume" | "abort"
    reason: str
    strike: int
    error_code: str
    ts: float


@dataclass(frozen=True)
class DoiGateFailureInfo:
    """One doi_gate_failure record (PRD §6.7.T2)."""

    doi: str
    crossref_status: int
    blocking: bool
    error_code: str
    ts: float


@dataclass(frozen=True)
class CascadeVerdictInfo:
    """One cascade_verdict record per stage (PRD §6.4)."""

    stage: str  # "A" | "B" | "C"
    verdict: str  # "pass" | "fail"
    score: float
    reason: str
    short_circuited: bool
    error_code: str | None
    ts: float


@dataclass(frozen=True)
class NoveltyVerdictInfo:
    """The latest novelty_gate_verdict for the run (PRD §6.1)."""

    verdict: str  # "novel" | "partial" | "redundant"
    max_similarity: float
    tau_warn: float
    tau_block: float
    n_neighbors: int
    error_code: str | None
    ts: float


@dataclass(frozen=True)
class EthicsChecklistInfo:
    """The latest ethics_checklist_result for the run (PRD §6.5)."""

    items_total: int
    items_pass: int
    items_fail: int
    items_na: int
    blocking: bool
    error_code: str | None
    ts: float


@dataclass(frozen=True)
class RunState:
    """Full dashboard state derived from an event stream."""

    run_id: str
    topic: str
    started_at: float | None
    resumed_count: int
    pipeline_status: str  # "pending" | "running" | "completed" | "error" | "watchdog_aborted"
    pipeline_error: str | None
    current_stage: str | None
    stages: Mapping[str, StageInfo]
    watchdog_actions: tuple[WatchdogAction, ...] = ()
    recovery_events: tuple[RecoveryEventInfo, ...] = ()
    doi_gate_failures: tuple[DoiGateFailureInfo, ...] = ()
    cascade_verdicts: tuple[CascadeVerdictInfo, ...] = ()
    novelty_verdict: NoveltyVerdictInfo | None = None
    ethics_checklist: EthicsChecklistInfo | None = None

    @classmethod
    def empty(cls) -> RunState:
        """Return a fresh RunState with no events applied."""
        return cls(
            run_id="",
            topic="",
            started_at=None,
            resumed_count=0,
            pipeline_status="pending",
            pipeline_error=None,
            current_stage=None,
            stages={},
            watchdog_actions=(),
            recovery_events=(),
            doi_gate_failures=(),
            cascade_verdicts=(),
            novelty_verdict=None,
            ethics_checklist=None,
        )


def read_events(path: Path) -> list[dict[str, Any]]:
    """Read JSONL events from a file. Malformed lines are skipped with a warning.

    Returns an empty list if the file does not exist. Never raises on bad data —
    the dashboard is a derived view, not a system of record.

    The schema_version first-line marker (PRD §6.8.T3) is filtered out — it is
    file metadata, not an event. Use ``validate_schema_version`` separately to
    enforce major-version compatibility.
    """
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed event at %s:%d: %s", path, lineno, exc)
                continue
            if record.get("event_type") == "schema_version":
                continue
            events.append(record)
    return events


def apply_event(state: RunState, event: dict[str, Any]) -> RunState:
    """Return a new RunState with one event applied.

    Pure function — does not mutate input state. Unknown event types return
    state unchanged for forward-compatibility.
    """
    event_type = event.get("type", "")

    if event_type == "pipeline_start":
        if state.started_at is None:
            return replace(
                state,
                run_id=event["run_id"],
                topic=event["topic"],
                started_at=event["ts"],
                pipeline_status="running",
            )
        return replace(
            state,
            resumed_count=state.resumed_count + 1,
            pipeline_status="running",
            pipeline_error=None,
        )

    if event_type == "stage_change":
        new_stage = event["stage"]
        ts = event["ts"]
        new_stages: dict[str, StageInfo] = dict(state.stages)
        if state.current_stage and state.current_stage in new_stages:
            prev = new_stages[state.current_stage]
            if prev.status == "running":
                new_stages[state.current_stage] = replace(prev, status="completed", ended_at=ts)
        if new_stage in new_stages:
            existing = new_stages[new_stage]
            new_stages[new_stage] = replace(existing, status="running")
        else:
            new_stages[new_stage] = StageInfo(
                name=new_stage,
                nodes=(),
                started_at=ts,
                ended_at=None,
                status="running",
            )
        return replace(state, current_stage=new_stage, stages=new_stages)

    if event_type in ("node_complete", "node_error"):
        stage_name = event["stage"]
        ts = event["ts"]
        new_stages = dict(state.stages)
        if stage_name not in new_stages:
            new_stages[stage_name] = StageInfo(
                name=stage_name,
                nodes=(),
                started_at=ts,
                ended_at=None,
                status="running",
            )
        existing = new_stages[stage_name]
        is_error = event_type == "node_error"
        node_info = NodeInfo(
            name=event["node"],
            scope=event["scope"],
            duration_s=event.get("duration_s", 0.0),
            status="error" if is_error else "completed",
            error=event.get("error") if is_error else None,
        )
        new_status = "error" if is_error else existing.status
        new_stages[stage_name] = replace(
            existing,
            nodes=(*existing.nodes, node_info),
            status=new_status,
        )
        return replace(state, stages=new_stages)

    if event_type == "pipeline_complete":
        ts = event["ts"]
        new_stages = dict(state.stages)
        if state.current_stage and state.current_stage in new_stages:
            cur = new_stages[state.current_stage]
            if cur.status == "running":
                new_stages[state.current_stage] = replace(cur, status="completed", ended_at=ts)
        return replace(state, pipeline_status="completed", stages=new_stages)

    if event_type == "pipeline_error":
        return replace(
            state,
            pipeline_status="error",
            pipeline_error=event.get("error", ""),
        )

    if event_type in (
        "watchdog_killing",
        "watchdog_killed",
        "watchdog_resuming",
        "watchdog_resumed",
        "watchdog_aborted",
    ):
        action = event_type.removeprefix("watchdog_")
        wa = WatchdogAction(
            action=action,
            ts=event.get("ts", 0.0),
            pgid=event.get("pgid"),
            age_s=event.get("age_s"),
            strike=event.get("strike"),
            reason=event.get("reason"),
            killed_cleanly=event.get("killed_cleanly"),
        )
        new_actions = (*state.watchdog_actions, wa)
        # watchdog_aborted = the safety net fired; the pipeline will not
        # be resumed again. Reflect in pipeline_status so render() can
        # surface it loudly.
        if action == "aborted":
            return replace(
                state,
                watchdog_actions=new_actions,
                pipeline_status="watchdog_aborted",
                pipeline_error=event.get("reason", "watchdog 3-strikes abort"),
            )
        return replace(state, watchdog_actions=new_actions)

    if event_type == "recovery_event":
        rec = RecoveryEventInfo(
            layer=event["layer"],
            action=event["action"],
            reason=event["reason"],
            strike=event["strike"],
            error_code=event["error_code"],
            ts=event.get("ts", 0.0),
        )
        return replace(state, recovery_events=(*state.recovery_events, rec))

    if event_type == "doi_gate_failure":
        dg = DoiGateFailureInfo(
            doi=event["doi"],
            crossref_status=event["crossref_status"],
            blocking=event["blocking"],
            error_code=event["error_code"],
            ts=event.get("ts", 0.0),
        )
        return replace(state, doi_gate_failures=(*state.doi_gate_failures, dg))

    if event_type == "cascade_verdict":
        cv = CascadeVerdictInfo(
            stage=event["stage"],
            verdict=event["verdict"],
            score=event["score"],
            reason=event["reason"],
            short_circuited=event["short_circuited"],
            error_code=event.get("error_code"),
            ts=event.get("ts", 0.0),
        )
        return replace(state, cascade_verdicts=(*state.cascade_verdicts, cv))

    if event_type == "novelty_gate_verdict":
        nv = NoveltyVerdictInfo(
            verdict=event["verdict"],
            max_similarity=event["max_similarity"],
            tau_warn=event["tau_warn"],
            tau_block=event["tau_block"],
            n_neighbors=len(event.get("neighbors", [])),
            error_code=event.get("error_code"),
            ts=event.get("ts", 0.0),
        )
        return replace(state, novelty_verdict=nv)

    if event_type == "ethics_checklist_result":
        ec = EthicsChecklistInfo(
            items_total=event["items_total"],
            items_pass=event["items_pass"],
            items_fail=event["items_fail"],
            items_na=event["items_na"],
            blocking=event["blocking"],
            error_code=event.get("error_code"),
            ts=event.get("ts", 0.0),
        )
        return replace(state, ethics_checklist=ec)

    return state


def derive_state(events: list[dict[str, Any]]) -> RunState:
    """Walk events in order, returning the final dashboard state.

    Equivalent to ``reduce(apply_event, events, RunState.empty())``.
    """
    return reduce(apply_event, events, RunState.empty())


_STATUS_ICON = {
    "pending": "[ ]",
    "running": ">>>",
    "completed": "[+]",
    "error": "[X]",
}


def _fmt_duration(seconds: float | None) -> str:
    """Format a duration in seconds as a compact human string."""
    if seconds is None or seconds <= 0:
        return ""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h = m // 60
    return f"{h}h{m % 60:02d}m"


def _stage_total_duration(stage: StageInfo) -> str:
    """Return the total wall-time for a stage, falling back to sum of node durations."""
    if stage.started_at and stage.ended_at:
        return _fmt_duration(stage.ended_at - stage.started_at)
    return _fmt_duration(sum(n.duration_s for n in stage.nodes))


def render(state: RunState) -> Panel:
    """Build a Rich Panel containing the dashboard view of the run state."""
    if state.run_id == "" and not state.stages and not state.watchdog_actions:
        return Panel(Text("no events recorded for this run"), title="ACADEMIC PIPELINE")

    header = Table.grid(padding=(0, 2))
    header.add_column(justify="right", style="bold")
    header.add_column()
    header.add_row("Topic:", state.topic or "—")
    header.add_row("Run:", state.run_id or "—")
    status = state.pipeline_status.upper()
    if state.current_stage:
        status += f"  ({state.current_stage})"
    if state.resumed_count:
        status += f"  resumed x{state.resumed_count}"
    header.add_row("Status:", status)
    if state.started_at:
        started = datetime.fromtimestamp(state.started_at, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
        header.add_row("Started:", started)

    stage_table = Table(show_header=True, header_style="bold")
    stage_table.add_column("", width=4)
    stage_table.add_column("Stage")
    stage_table.add_column("Nodes", justify="right")
    stage_table.add_column("Duration", justify="right")
    stage_table.add_column("Last node")
    for stage_id in STAGE_DISPLAY_ORDER:
        info = state.stages.get(stage_id)
        if info is None:
            stage_table.add_row(_STATUS_ICON["pending"], Text(stage_id, style="dim"), "0", "", "", style="dim")
            continue
        last_name = info.nodes[-1].name if info.nodes else ""
        style = "red" if info.status == "error" else None
        stage_table.add_row(
            _STATUS_ICON.get(info.status, "?"),
            stage_id,
            str(len(info.nodes)),
            _stage_total_duration(info),
            last_name,
            style=style,
        )

    parts: list[Any] = [header, stage_table]

    if state.pipeline_status == "running" and state.current_stage:
        active = state.stages.get(state.current_stage)
        if active and active.nodes:
            detail = Table(show_header=False, padding=(0, 1))
            detail.add_column("", style="dim", width=2)
            detail.add_column()
            detail.add_column(justify="right")
            for node in active.nodes:
                icon = _STATUS_ICON["error" if node.status == "error" else "completed"]
                detail.add_row(icon, node.name, _fmt_duration(node.duration_s))
            parts.append(Panel(detail, title=f"current: {state.current_stage}", border_style="dim"))

    if state.pipeline_status == "error" and state.pipeline_error:
        parts.append(Panel(Text(state.pipeline_error, style="bold red"), title="ERROR", border_style="red"))

    if state.watchdog_actions:
        wd_table = Table(show_header=True, header_style="bold yellow", padding=(0, 1))
        wd_table.add_column("Action")
        wd_table.add_column("Strike", justify="right")
        wd_table.add_column("Age (s)", justify="right")
        wd_table.add_column("Note")
        for wa in state.watchdog_actions:
            note_parts: list[str] = []
            if wa.pgid is not None:
                note_parts.append(f"pgid={wa.pgid}")
            if wa.killed_cleanly is False:
                note_parts.append("KILL FAILED")
            if wa.reason:
                note_parts.append(wa.reason)
            wd_table.add_row(
                wa.action,
                str(wa.strike) if wa.strike is not None else "",
                f"{wa.age_s:.0f}" if wa.age_s is not None else "",
                ", ".join(note_parts),
            )
        border = "red" if state.pipeline_status == "watchdog_aborted" else "yellow"
        parts.append(Panel(wd_table, title="watchdog", border_style=border))

    if state.recovery_events:
        rec_table = Table(show_header=True, header_style="bold magenta", padding=(0, 1))
        rec_table.add_column("Layer", justify="right")
        rec_table.add_column("Action")
        rec_table.add_column("Strike", justify="right")
        rec_table.add_column("Code")
        rec_table.add_column("Reason")
        for rec in state.recovery_events:
            rec_table.add_row(
                str(rec.layer),
                rec.action,
                str(rec.strike),
                rec.error_code,
                rec.reason,
            )
        title = f"recovery (count={len(state.recovery_events)})"
        parts.append(Panel(rec_table, title=title, border_style="magenta"))

    if state.cascade_verdicts:
        cas_table = Table(show_header=True, header_style="bold cyan", padding=(0, 1))
        cas_table.add_column("Stage")
        cas_table.add_column("Verdict")
        cas_table.add_column("Score", justify="right")
        cas_table.add_column("Short-circuit")
        cas_table.add_column("Reason")
        for cv in state.cascade_verdicts:
            cas_table.add_row(
                cv.stage,
                cv.verdict,
                f"{cv.score:.2f}",
                "yes" if cv.short_circuited else "",
                cv.reason,
            )
        parts.append(Panel(cas_table, title="cascade verdicts", border_style="cyan"))

    if state.novelty_verdict is not None:
        nv = state.novelty_verdict
        nv_grid = Table.grid(padding=(0, 2))
        nv_grid.add_column(justify="right", style="bold")
        nv_grid.add_column()
        nv_grid.add_row("Verdict:", nv.verdict)
        nv_grid.add_row("Max similarity:", f"{nv.max_similarity:.2f}")
        nv_grid.add_row("τ_warn / τ_block:", f"{nv.tau_warn:.2f} / {nv.tau_block:.2f}")
        nv_grid.add_row("Neighbors checked:", str(nv.n_neighbors))
        if nv.error_code:
            nv_grid.add_row("Error code:", nv.error_code)
        nv_border = "green" if nv.verdict == "novel" else "yellow" if nv.verdict == "partial" else "red"
        parts.append(Panel(nv_grid, title="novelty gate", border_style=nv_border))

    if state.ethics_checklist is not None:
        ec = state.ethics_checklist
        ec_grid = Table.grid(padding=(0, 2))
        ec_grid.add_column(justify="right", style="bold")
        ec_grid.add_column()
        ec_grid.add_row("Pass / total:", f"{ec.items_pass} / {ec.items_total}")
        if ec.items_fail:
            ec_grid.add_row("Failed:", str(ec.items_fail))
        if ec.items_na:
            ec_grid.add_row("N/A:", str(ec.items_na))
        if ec.blocking and ec.items_fail:
            ec_grid.add_row("Blocking:", "YES")
        if ec.error_code:
            ec_grid.add_row("Error code:", ec.error_code)
        ec_border = "red" if (ec.blocking and ec.items_fail) else "green"
        parts.append(Panel(ec_grid, title="ethics checklist", border_style=ec_border))

    if state.doi_gate_failures:
        doi_table = Table(show_header=True, header_style="bold red", padding=(0, 1))
        doi_table.add_column("DOI")
        doi_table.add_column("CrossRef", justify="right")
        doi_table.add_column("Blocking")
        doi_table.add_column("Code")
        for dg in state.doi_gate_failures:
            doi_table.add_row(
                dg.doi,
                str(dg.crossref_status),
                "YES" if dg.blocking else "no",
                dg.error_code,
            )
        parts.append(Panel(doi_table, title="DOI gate failures", border_style="red"))

    return Panel(Group(*parts), title="ACADEMIC PIPELINE")


def latest_run_dir(output_root: Path) -> Path | None:
    """Resolve `<output_root>/latest` symlink to its target dir, or None if missing."""
    link = output_root / "latest"
    if not link.exists():
        return None
    return link.resolve()
