"""Replay an events.jsonl log into a RunState and render the dashboard.

Demonstrates the dashboard's pure-renderer contract: the events.jsonl emitted
by every Pipeline run is a complete event stream, and `runtime.dashboard`
provides `read_events`, `apply_event`, `derive_state`, and `render` so any
historical run can be re-rendered without re-running the pipeline.

Useful for: post-mortems, screenshotting old runs, exporting state to other
tools, building custom dashboards.

PRD §6.12.T3 + §6.8 (dashboard).

Run:
    uv run python examples/replay_from_events_jsonl.py path/to/events.jsonl
    uv run python examples/replay_from_events_jsonl.py --dry-run     # CI smoke
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def _is_dry_run() -> bool:
    return "--dry-run" in sys.argv[1:]


def main() -> int:
    """Replay an events.jsonl file into the dashboard (use --dry-run for CI smoke)."""
    if _is_dry_run():
        # Synthesize a minimal events.jsonl in a temp dir and replay it. This
        # is the CI smoke path — exercises the full read/derive/render chain
        # without needing an existing run on disk.
        from academic_pipeline.runtime.dashboard import derive_state, read_events, render

        with tempfile.TemporaryDirectory() as td:
            events_path = Path(td) / "events.jsonl"
            events_path.write_text(
                json.dumps({"type": "pipeline_start", "ts": 0.0, "run_id": "x", "topic": "y", "resumed": False})
                + "\n"
                + json.dumps({"type": "stage_change", "ts": 1.0, "stage": "research", "previous": None})
                + "\n"
                + json.dumps({"type": "pipeline_complete", "ts": 2.0})
                + "\n"
            )
            state = derive_state(read_events(events_path))
            _ = render(state)  # rendered Rich object — discarded in dry-run
        print("dry-run OK — synthesized + rendered a 3-event stream")
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: replay_from_events_jsonl.py path/to/events.jsonl")
        return 2

    from rich.console import Console

    from academic_pipeline.runtime.dashboard import derive_state, read_events, render

    events_path = Path(args[0])
    if not events_path.exists():
        print(f"error: {events_path} does not exist")
        return 2

    state = derive_state(read_events(events_path))
    Console(width=120).print(render(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
