"""Typer CLI for the Academic Research Pipeline.

Parses user input (topic) and displays pipeline results.
Delegates execution to the Pipeline SDK.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Annotated, Any

import typer

from academic_pipeline.logging_config import configure_logging
from academic_pipeline.persistence import SqliteStatePersistence


app = typer.Typer(
    name="academic-pipeline",
    help=(
        "Academic Research Pipeline — give it a topic, get a journal-ready paper.\n\n"
        "Each node is quality-gated by a multi-model evaluation panel (GPT-5.2, Opus 4.6). "
        "Use --no-eval to skip evaluation for faster runs."
    ),
    no_args_is_help=True,
)


class CheckpointerBackend(StrEnum):
    """Supported checkpoint storage backends."""

    MEMORY = "memory"
    SQLITE = "sqlite"
    POSTGRES = "postgres"


def _init(
    checkpointer: CheckpointerBackend | None,
    verbose: bool,
    json_logs: bool,
    *,
    no_eval: bool = False,
    durable: bool = False,
    force_experiment: bool = False,
) -> None:
    """Configure SSL, set up logging and observability."""
    from academic_pipeline.observability import (
        configure_observability,
        configure_ssl,
        init_dbos,
        shutdown_observability,
    )

    configure_ssl()

    if no_eval:
        import os

        os.environ["ENABLE_NODE_EVALUATION"] = "false"

    if force_experiment:
        import os

        os.environ["FORCE_EXPERIMENT"] = "true"

    from academic_pipeline.config import DEFAULT_CONFIG

    configure_logging(
        verbose,
        json_logs=json_logs,
        log_dir=DEFAULT_CONFIG.log_dir,
        max_bytes=DEFAULT_CONFIG.log_max_bytes,
        backup_count=DEFAULT_CONFIG.log_backup_count,
    )

    import atexit

    atexit.register(shutdown_observability)

    configure_observability()
    if durable:
        _cli_state["dbos"] = init_dbos()


_cli_state: dict[str, bool] = {"dbos": False}


def _parse_authors(raw: list[str] | None) -> list[dict[str, str]]:
    """Parse ['Name | Affil | email'] into [{name, affiliation, email}]."""
    if not raw:
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        parts = [p.strip() for p in item.split("|")]
        record: dict[str, str] = {
            "name": parts[0],
            "affiliation": parts[1] if len(parts) > 1 else "",
        }
        if len(parts) > 2 and parts[2]:
            record["email"] = parts[2]
        out.append(record)
    return out


def _make_pipeline(
    topic: str,
    revision: str = "",
    authors: list[str] | None = None,
    copilot: bool = False,
) -> Any:
    """Lazy-import and construct a Pipeline instance."""
    from academic_pipeline.models.shared import Author
    from academic_pipeline.models.writing import PaperConfig
    from academic_pipeline.sdk.pipeline import Pipeline

    paper_config: PaperConfig | None = None
    parsed_authors = _parse_authors(authors)
    if parsed_authors:
        author_models = [
            Author(
                name=a["name"],
                affiliation=a.get("affiliation", ""),
                email=a.get("email", ""),
            )
            for a in parsed_authors
        ]
        paper_config = PaperConfig(
            topic=topic,
            research_question="",  # populated by intake agent
            paper_type="IMRaD",
            discipline="",
            target_journal="",
            citation_format="APA7",
            word_count_target=0,
            writing_task="full-paper",
            authors=author_models,
        )

    pipeline = Pipeline(
        topic,
        revision_instructions=revision,
        paper_config=paper_config,
        use_dbos=_cli_state["dbos"],
    )

    if copilot:
        # Override config on the deps with copilot_enabled=True so checkpoint
        # call sites in pipeline/nodes.py exercise their stdin-prompt branch.
        pipeline._deps.config = pipeline._deps.config.model_copy(update={"copilot_enabled": True})

    if _cli_state["dbos"]:
        from academic_pipeline.observability import launch_dbos

        launch_dbos()

    return pipeline


def _run_and_show(pipeline: Any, output_dir: str | None) -> None:
    """Execute the pipeline and display results."""
    import sys

    print("Starting pipeline...", file=sys.stderr, flush=True)
    try:
        asyncio.run(pipeline.run(output_dir=output_dir))
        if output_dir:
            typer.echo(f"Artifacts saved to {output_dir}")
    except Exception as exc:
        typer.echo(f"Pipeline failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# --- Shared option types ---

TopicArg = Annotated[str, typer.Argument(help="Research topic")]
CheckpointerOpt = Annotated[CheckpointerBackend | None, typer.Option(help="Checkpointer backend")]
OutputOpt = Annotated[str | None, typer.Option(help="Save artifacts to this directory")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging")]
JsonLogsOpt = Annotated[bool, typer.Option(help="Structured JSON logging")]
RevisionOpt = Annotated[str | None, typer.Option(help="Revision instructions for guided re-run")]
NoEvalOpt = Annotated[
    bool, typer.Option("--no-eval", help="Skip multi-model evaluation panel (faster, less quality gating)")
]
DurableOpt = Annotated[bool, typer.Option("--durable", help="Enable DBOS durable execution for crash recovery")]
ForceExpOpt = Annotated[bool, typer.Option("--force-experiment", help="Skip classifier and force experiment phase")]
AuthorOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--author",
        "-a",
        help='Paper author. Format: "Name | Affiliation | email" (affiliation/email optional). Repeatable.',
    ),
]
CopilotOpt = Annotated[
    bool,
    typer.Option(
        "--copilot",
        help=(
            "Enable interactive copilot checkpoints (post-intake, post-experiment, "
            "post-first-draft). Each checkpoint pauses for an optional 1-sentence "
            "stdin comment with 60s timeout."
        ),
    ),
]


@app.command()
def run(
    topic: TopicArg,
    output_dir: OutputOpt = None,
    checkpointer: CheckpointerOpt = None,
    verbose: VerboseOpt = False,
    json_logs: JsonLogsOpt = False,
    revision: RevisionOpt = None,
    no_eval: NoEvalOpt = False,
    durable: DurableOpt = False,
    force_experiment: ForceExpOpt = False,
    authors: AuthorOpt = None,
    copilot: CopilotOpt = False,
) -> None:
    """Run the full academic pipeline (research -> write -> review -> finalize).

    Each research node is quality-gated by a multi-model evaluation panel.
    Use --no-eval to skip evaluation for faster runs (~90 min vs ~120 min).
    Use --durable to enable DBOS crash recovery. Use --force-experiment to
    bypass the classifier and always run the experiment phase.
    """
    _init(checkpointer, verbose, json_logs, no_eval=no_eval, durable=durable, force_experiment=force_experiment)
    _run_and_show(
        _make_pipeline(topic, revision=revision or "", authors=authors, copilot=copilot),
        output_dir,
    )


@app.command()
def resume(
    thread_id: Annotated[str, typer.Argument(help="Thread ID from a previous run (use 'make list-runs' to find)")],
    output_dir: OutputOpt = None,
    verbose: VerboseOpt = False,
    json_logs: JsonLogsOpt = False,
    no_eval: NoEvalOpt = False,
    force_experiment: ForceExpOpt = False,
) -> None:
    """Resume a crashed or interrupted pipeline run.

    Loads the topic from saved state — no need to re-type it.
    Use 'make list-runs' to see available thread IDs.
    """
    import json
    from pathlib import Path

    db_path = Path(".pipeline_runs/pipeline.sqlite")
    if not db_path.exists():
        typer.echo(f"No pipeline database found at {db_path}", err=True)
        raise typer.Exit(1)

    persistence = SqliteStatePersistence(db_path=db_path, run_id=thread_id)
    state_json = persistence._load_pipeline_state_sync(thread_id)
    if state_json is None:
        typer.echo(f"No saved state found for thread-id: {thread_id}", err=True)
        raise typer.Exit(1)

    topic = json.loads(state_json).get("topic", "")
    if not topic:
        typer.echo(f"No topic found in saved state for: {thread_id}", err=True)
        raise typer.Exit(1)

    _init(None, verbose, json_logs, no_eval=no_eval, force_experiment=force_experiment)

    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline(topic, thread_id=thread_id, use_dbos=_cli_state["dbos"])
    _run_and_show(pipeline, output_dir or "./output")


@app.command()
def dashboard(
    run_id: str | None = typer.Argument(None, help="Run ID to view, or omit to use --latest"),
    latest: bool = typer.Option(False, "--latest", help="View the most recent run (resolves output/latest symlink)"),
    watch: bool = typer.Option(False, "--watch", help="Live mode: refresh every second until Ctrl-C"),
    output_dir: str = typer.Option("output", "--output-dir", help="Root directory containing per-run subdirectories"),
) -> None:
    """Render the events-driven pipeline dashboard."""
    from pathlib import Path as _Path

    from rich.console import Console
    from rich.live import Live

    from academic_pipeline.runtime.dashboard import (
        SchemaVersionMismatch,
        derive_state,
        latest_run_dir,
        read_events,
        render,
        validate_schema_version,
    )

    output_root = _Path(output_dir)
    if latest or run_id is None:
        target = latest_run_dir(output_root)
        if target is None:
            typer.echo(f"No latest run found under {output_root}/", err=True)
            raise typer.Exit(code=1)
    else:
        target = output_root / run_id
        if not target.exists():
            typer.echo(f"Run directory not found: {target}", err=True)
            raise typer.Exit(code=1)

    events_path = target / "events.jsonl"
    # Renderer rejects incompatible schemas (PRD §6.8.T3). Pre-v2.5.0 files
    # without a schema_version marker are also rejected per R21.
    try:
        validate_schema_version(events_path)
    except SchemaVersionMismatch as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    console = Console()

    def _snapshot() -> None:
        state = derive_state(read_events(events_path))
        console.print(render(state))

    if not watch:
        _snapshot()
        return

    state = derive_state(read_events(events_path))
    with Live(render(state), console=console, refresh_per_second=1, screen=False) as live:
        try:
            while True:
                import time as _time

                _time.sleep(1.0)
                state = derive_state(read_events(events_path))
                live.update(render(state))
        except KeyboardInterrupt:
            pass


@app.command(name="watchdog")
def watchdog_cmd(
    thread_id: str = typer.Argument(..., help="Run ID to monitor"),
    max_idle: int = typer.Option(600, "--max-idle", help="Seconds of stall before kill (default 600 = 10min)"),
    poll: int = typer.Option(15, "--poll", help="Seconds between checks"),
    output_dir: str = typer.Option("output", "--output-dir"),
    persistence_dir: str = typer.Option(".pipeline_runs", "--persistence-dir"),
    auto_resume: bool = typer.Option(False, "--auto-resume"),
    max_recoveries: int = typer.Option(
        3,
        "--max-recoveries",
        help="Max consecutive kill+resume cycles before aborting (PRD §6.6.T1).",
    ),
    max_strikes: int = typer.Option(
        3,
        "--max-strikes",
        hidden=True,
        help="Legacy alias for --max-recoveries (kept for backward compat).",
    ),
) -> None:
    """Watch a running pipeline for stalls; SIGTERM/KILL + resume on stall."""
    from pathlib import Path

    from academic_pipeline.config import DEFAULT_CONFIG
    from academic_pipeline.recovery.watchdog import WatchdogConfig, run_watchdog

    configure_logging(
        verbose=False,
        log_dir=DEFAULT_CONFIG.log_dir,
        max_bytes=DEFAULT_CONFIG.log_max_bytes,
        backup_count=DEFAULT_CONFIG.log_backup_count,
    )

    # Prefer the new --max-recoveries flag; fall back to legacy --max-strikes
    # only when the new flag was left at its default.
    effective_strikes = max_recoveries if max_recoveries != 3 else max_strikes
    cfg = WatchdogConfig(
        thread_id=thread_id,
        max_idle_s=max_idle,
        poll_interval_s=poll,
        output_dir=Path(output_dir),
        persistence_dir=Path(persistence_dir),
        auto_resume=auto_resume,
        max_strikes=effective_strikes,
    )
    raise typer.Exit(code=run_watchdog(cfg))


@app.command(name="supervised-run")
def supervised_run_cmd(
    topic: str = typer.Argument(..., help="Research topic"),
    force_experiment: bool = typer.Option(False, "--force-experiment"),
    output_dir: str = typer.Option("output", "--output-dir"),
    no_watchdog: bool = typer.Option(False, "--no-watchdog", help="Run without watchdog (for debugging)"),
    quiet: bool = typer.Option(False, "--quiet", help="Skip --verbose on the wrapped pipeline run"),
    copilot: bool = typer.Option(
        False,
        "--copilot",
        help=(
            "Enable interactive copilot checkpoints on the wrapped pipeline. "
            "Forwarded as --copilot to the subprocess `run` invocation."
        ),
    ),
    max_recoveries: int = typer.Option(
        3,
        "--max-recoveries",
        help="Max consecutive kill+resume cycles before aborting (PRD §6.6.T1).",
    ),
) -> None:
    """Run the pipeline under a supervisor that auto-recovers from hangs."""
    from academic_pipeline.config import DEFAULT_CONFIG
    from academic_pipeline.recovery.supervisor import supervised_run

    configure_logging(
        verbose=not quiet,
        log_dir=DEFAULT_CONFIG.log_dir,
        max_bytes=DEFAULT_CONFIG.log_max_bytes,
        backup_count=DEFAULT_CONFIG.log_backup_count,
    )

    args: list[str] = [topic]
    if force_experiment:
        args.append("--force-experiment")
    if copilot:
        args.append("--copilot")
    raise typer.Exit(
        code=supervised_run(
            *args,
            output_dir=output_dir,
            no_watchdog=no_watchdog,
            verbose=not quiet,
            max_recoveries=max_recoveries,
        )
    )


@app.command(name="cleanup-state")
def cleanup_state_cmd(
    pipeline_runs_dir: str = typer.Option(
        ".pipeline_runs",
        "--pipeline-runs-dir",
        help="Path to the .pipeline_runs/ root.",
    ),
    before: str = typer.Option(
        "2.5.0",
        "--before",
        help="Version cutoff label (informational; scope is v2.4.0 → v2.5.0 per PRD OQ17).",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Take action. Without this flag the command is a dry-run (safe default).",
    ),
    purge: bool = typer.Option(
        False,
        "--purge",
        help="Delete incompatible files outright instead of archiving (default: archive).",
    ),
) -> None:
    """Archive/purge incompatible PipelineState files.

    Walks .pipeline_runs/ for state files whose `_schema_version` is missing
    or differs from PIPELINE_STATE_SCHEMA_VERSION, archives or purges them,
    and prints a summary. Default is dry-run + archive (no destructive action
    without --confirm; never deletes without --purge). PRD §6.9.T5.
    """
    import sys
    from pathlib import Path

    # Tools live at repo root; sys.path may not include it. Resolve by
    # importing via the file's parent dir if the module isn't already
    # importable.
    try:
        from tools.cleanup_state import _format_report, cleanup_state
    except ImportError:
        repo_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(repo_root))
        from tools.cleanup_state import _format_report, cleanup_state

    summary = cleanup_state(
        pipeline_runs_dir=Path(pipeline_runs_dir),
        confirm=confirm,
        purge=purge,
    )
    typer.echo(_format_report(summary, confirmed=confirm, purged=purge), err=True)
    if not confirm and summary.incompatible_count > 0:
        # Exit 1 in dry-run mode if there's anything to clean up so CI
        # workflows can detect "needs cleanup" without the user running
        # --confirm. Idempotent runs (no-op) exit 0.
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@app.command(name="unseal-run")
def unseal_run_cmd(
    thread_id: str = typer.Argument(..., help="Thread ID of a sealed-by-AbortNode run"),
    delete_terminal_snapshots: bool = typer.Option(
        True,
        "--delete-terminal-snapshots/--keep-terminal-snapshots",
        help="Delete AbortNode + terminal End snapshots so load_next() finds work to do.",
    ),
    persistence_dir: str = typer.Option(
        ".pipeline_runs", "--persistence-dir", help="Directory containing pipeline.sqlite"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing"),
) -> None:
    """Un-seal a run that AbortNode marked terminal so it can be resumed.

    Pre-fix runs (and any run that hit AbortNode for any reason) end up with:
      - pipeline_status = ABORTED in pipeline_state
      - AbortNode snapshot status='success'
      - Terminal End snapshots in 'created' status

    pydantic_graph.load_next() returns None on this state -> resume fails with
    "Unable to restore snapshot from state persistence". This command:
      1. Deletes the AbortNode + terminal End snapshots (so load_next looks
         further back and finds the last 'success' real-work node).
      2. Resets pipeline_status from ABORTED to RUNNING in pipeline_state.
      3. Resets the OUTER pipeline-level snapshot for the phase that aborted
         from 'success' back to 'created' so it re-runs (and its inner
         subgraph snapshots are preserved → real resume).

    After unseal, run `make resume THREAD_ID=<id>` to continue.
    """
    import json
    import sqlite3
    from pathlib import Path as _Path

    db = _Path(persistence_dir) / "pipeline.sqlite"
    if not db.exists():
        typer.echo(f"No SQLite DB at {db}", err=True)
        raise typer.Exit(code=1)

    conn = sqlite3.connect(str(db))
    try:
        # Outer pipeline first — find AbortNode snapshot + the phase node that
        # produced it. Walk DESC so the first non-end/non-Abort success row IS
        # the phase that called AbortNode (e.g. ExperimentPhaseNode).
        outer = conn.execute(
            "SELECT id, snapshot_id, status FROM snapshots WHERE run_id = ? ORDER BY id DESC",
            (thread_id,),
        ).fetchall()
        if not outer:
            typer.echo(f"No outer snapshots for {thread_id}", err=True)
            raise typer.Exit(code=1)

        outer_terminal = [
            row[0]
            for row in outer
            if row[2] in ("created", "success") and (row[1].startswith("end:") or row[1].startswith("AbortNode:"))
        ]
        outer_phase = next(
            (row for row in outer if row[2] == "success" and not row[1].startswith(("end:", "AbortNode:"))),
            None,
        )
        if outer_phase is None:
            typer.echo("No phase snapshot to un-seal (no real-work success)", err=True)
            raise typer.Exit(code=1)

        outer_phase_name = outer_phase[1].split(":", 1)[0]

        # Map phase node → subgraph run_id suffix. Only the subgraph for the
        # aborting phase is touched; other subgraphs that completed cleanly
        # (research, etc.) are left alone so their work isn't repeated.
        phase_to_subgraph_suffix = {
            "ResearchPhaseNode": "_research",
            "ExperimentPhaseNode": "_experiment",
            "WritePhaseNode": "_write",
            "PreIntegrityNode": "_pre_integrity_0",
            "ReviewPhaseNode": "_review",
            "FinalIntegrityNode": "_final_integrity_0",
        }
        sub_run_id: str | None = None
        sub_terminal: list[int] = []
        sub_last_success: tuple[int, str] | None = None
        suffix = phase_to_subgraph_suffix.get(outer_phase_name)
        if suffix:
            candidate_run = thread_id + suffix
            sub_rows = conn.execute(
                "SELECT id, snapshot_id, status FROM snapshots " "WHERE run_id = ? ORDER BY id DESC",
                (candidate_run,),
            ).fetchall()
            if sub_rows:
                sub_run_id = candidate_run
                sub_terminal = [
                    row[0] for row in sub_rows if row[2] in ("created", "success") and row[1].startswith("end:")
                ]
                last = next(
                    (row for row in sub_rows if row[2] == "success" and not row[1].startswith("end:")),
                    None,
                )
                if last is not None:
                    sub_last_success = (last[0], last[1])

        # pipeline_state.pipeline_status
        row = conn.execute(
            "SELECT state_json FROM pipeline_state WHERE run_id = ?",
            (thread_id,),
        ).fetchone()
        current_status = json.loads(row[0]).get("pipeline_status") if row else None

        typer.echo(f"Run {thread_id}:")
        typer.echo(f"  pipeline_status = {current_status}")
        typer.echo(f"  outer phase that aborted: {outer_phase_name}")
        typer.echo(f"  outer terminal snapshots to delete: {outer_terminal}")
        typer.echo(f"  outer phase reset to 'created': id={outer_phase[0]} ({outer_phase[1]})")
        if sub_run_id:
            typer.echo(f"  inner subgraph: {sub_run_id}")
            typer.echo(f"    terminal End snapshots to delete: {sub_terminal or '(none)'}")
            if sub_last_success:
                typer.echo(
                    f"    last real-work snapshot kept as success (will resume from): "
                    f"id={sub_last_success[0]} ({sub_last_success[1]})"
                )

        if dry_run:
            typer.echo("\n--dry-run: no changes written.")
            return

        def _set_status_created(snap_id: int) -> None:
            """Reset both column and embedded JSON status to 'created'.

            Resets both the SQLite `status` column AND the embedded
            `data_json.status` field. pydantic-graph reads the embedded JSON
            via TypeAdapter, so updating only the column is silently ignored.
            """
            row = conn.execute("SELECT data_json FROM snapshots WHERE id = ?", (snap_id,)).fetchone()
            if not row:
                return
            data = json.loads(row[0])
            data["status"] = "created"
            # pydantic-graph also clears these on a fresh-created snapshot
            data["start_ts"] = None
            data["duration"] = None
            conn.execute(
                "UPDATE snapshots SET status = 'created', data_json = ?, "
                "start_ts = NULL, duration = NULL WHERE id = ?",
                (json.dumps(data), snap_id),
            )

        if delete_terminal_snapshots and outer_terminal:
            conn.executemany(
                "DELETE FROM snapshots WHERE id = ?",
                [(i,) for i in outer_terminal],
            )
        _set_status_created(outer_phase[0])
        if delete_terminal_snapshots and sub_terminal:
            conn.executemany(
                "DELETE FROM snapshots WHERE id = ?",
                [(i,) for i in sub_terminal],
            )
        # Reset the last real-work success snapshot in the subgraph too.
        # Otherwise pydantic-graph load_next() returns None (no 'created'
        # snapshots in the subgraph) → "Unable to restore snapshot from state
        # persistence" inside the subgraph. Re-running the last node is
        # idempotent for the work it does (its outputs are already in state)
        # and lets the routing decision re-fire to enqueue the next node.
        if sub_last_success is not None:
            _set_status_created(sub_last_success[0])
        if current_status == "aborted" and row is not None:
            state_data = json.loads(row[0])
            state_data["pipeline_status"] = "running"
            conn.execute(
                "UPDATE pipeline_state SET state_json = ? WHERE run_id = ?",
                (json.dumps(state_data), thread_id),
            )

        conn.commit()
        typer.echo(f"\nUn-sealed. Run `make resume THREAD_ID={thread_id}` to continue.")
    finally:
        conn.close()


@app.command(name="supervised-resume")
def supervised_resume_cmd(
    thread_id: str = typer.Argument(..., help="Thread ID from a previous crashed run"),
    output_dir: str = typer.Option("output", "--output-dir"),
    no_watchdog: bool = typer.Option(False, "--no-watchdog", help="Run without watchdog (for debugging)"),
    quiet: bool = typer.Option(False, "--quiet", help="Skip --verbose on the wrapped pipeline run"),
) -> None:
    """Resume a crashed run under a supervisor that auto-recovers from re-hangs.

    Use this instead of ``resume`` when the resumed pipeline itself might hang
    again — the watchdog will catch and restart it.
    """
    from academic_pipeline.config import DEFAULT_CONFIG
    from academic_pipeline.recovery.supervisor import supervised_run

    configure_logging(
        verbose=not quiet,
        log_dir=DEFAULT_CONFIG.log_dir,
        max_bytes=DEFAULT_CONFIG.log_max_bytes,
        backup_count=DEFAULT_CONFIG.log_backup_count,
    )

    raise typer.Exit(
        code=supervised_run(
            thread_id,
            output_dir=output_dir,
            no_watchdog=no_watchdog,
            subcommand="resume",
            verbose=not quiet,
        )
    )
