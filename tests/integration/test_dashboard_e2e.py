"""End-to-end smoke for the events-driven dashboard surface.

Exercises:
- Pipeline emits the expected event sequence to events.jsonl during a run.
- read_events + derive_state on that file reproduces the same RunState
  Pipeline maintained in memory.
- render() produces non-empty Rich output for that state.
- The `dashboard` CLI subcommand renders a synthetic events file end-to-end.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch


if TYPE_CHECKING:
    from pathlib import Path


def test_pipeline_run_produces_events_jsonl_replayable_via_derive_state(tmp_path: Path) -> None:
    """End-to-end: a Pipeline.run_stream cycle writes events, replay matches in-memory state."""
    from academic_pipeline.runtime.dashboard import derive_state, read_events, render
    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline(
        "e2e topic",
        thread_id="t-e2e",
        interactive=False,
        persistence_dir=tmp_path,
    )
    out = tmp_path / "out"

    async def _run() -> None:
        async for _ in pipeline.run_stream(output_dir=str(out)):
            pass

    # Use a synthetic graph error to keep the test fast and deterministic;
    # verifies that pipeline_start and pipeline_error events are written.
    with patch("academic_pipeline.pipeline.graph.build_pipeline_graph") as mock_build:
        mock_build.side_effect = RuntimeError("synthetic e2e exit")
        with contextlib.suppress(RuntimeError):
            asyncio.run(_run())

    events_path = out / "t-e2e" / "events.jsonl"
    assert events_path.exists(), f"events.jsonl missing at {events_path}"

    events = read_events(events_path)
    types = [e["type"] for e in events]
    assert "pipeline_start" in types
    assert "pipeline_error" in types

    # Replay must equal in-memory state
    disk_state = derive_state(events)
    assert pipeline._run_state == disk_state
    assert disk_state.pipeline_status == "error"
    assert "synthetic e2e exit" in (disk_state.pipeline_error or "")

    # Render produces non-empty output
    from rich.console import Console

    console = Console(width=120, record=True)
    console.print(render(disk_state))
    text = console.export_text()
    assert "e2e topic" in text
    assert "ERROR" in text.upper()


def test_dashboard_cli_renders_synthetic_run(tmp_path: Path) -> None:
    """The `dashboard` CLI subcommand reads a synthetic events.jsonl and prints a Panel."""
    run_dir = tmp_path / "run-e2e"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                # schema_version marker required by validate_schema_version (PRD §6.8.T3)
                json.dumps({"event_type": "schema_version", "version": "2.5.0"}),
                json.dumps(
                    {
                        "ts": 100.0,
                        "type": "pipeline_start",
                        "run_id": "run-e2e",
                        "topic": "CLI smoke",
                        "resumed": False,
                    }
                ),
                json.dumps({"ts": 110.0, "type": "stage_change", "stage": "research", "previous": None}),
                json.dumps(
                    {
                        "ts": 120.0,
                        "type": "node_complete",
                        "stage": "research",
                        "node": "RQClarifierNode",
                        "scope": "subgraph",
                        "duration_s": 5.0,
                    }
                ),
                json.dumps(
                    {
                        "ts": 130.0,
                        "type": "node_complete",
                        "stage": "research",
                        "node": "BibliographyBuilderNode",
                        "scope": "subgraph",
                        "duration_s": 8.0,
                    }
                ),
                json.dumps({"ts": 200.0, "type": "stage_change", "stage": "write", "previous": "research"}),
                json.dumps({"ts": 300.0, "type": "pipeline_complete"}),
            ]
        )
        + "\n"
    )
    # Symlink for --latest
    (tmp_path / "latest").symlink_to(run_dir.name)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "academic_pipeline",
            "dashboard",
            "--latest",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
    assert "CLI smoke" in proc.stdout
    assert "research" in proc.stdout.lower()
    assert "write" in proc.stdout.lower()
    # Either COMPLETED status or close enough — confirm the panel renders
    assert "ACADEMIC PIPELINE" in proc.stdout
