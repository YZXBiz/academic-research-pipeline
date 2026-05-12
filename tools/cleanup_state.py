"""Archive/purge incompatible PipelineState files in `.pipeline_runs/`.

Walks `.pipeline_runs/` for `*.json` state files and identifies any whose
`_schema_version` is missing or differs from `PIPELINE_STATE_SCHEMA_VERSION`.

Default mode is **archive**: incompatible files move to
`.pipeline_runs/_archive/<timestamp>/` so the operator can recover if a
mistake was made (PRD AP30 + §28 — never `rm` user data without a copy).
Pass `--purge` to actually delete instead of archive.

Pass `--confirm` to take any action; without it the script reports what
*would* happen but moves nothing (dry-run is the safe default).

Scope: v2.4.0 → v2.5.0 only per PRD §29 OQ17. Files inside the existing
`_archive/` subdir are skipped on subsequent runs (idempotent).

Wired into the CLI as `python -m academic_pipeline cleanup-state`
(PRD §6.9.T5). Error-code namespace: PRD §17 PRS.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CleanupSummary:
    """Result of a cleanup_state() run."""

    incompatible_count: int = 0
    incompatible_files: list[Path] = field(default_factory=list)
    archived_count: int = 0
    purged_count: int = 0


def _is_incompatible(state_path: Path, current_version: int) -> bool:
    """Return True if the JSON file lacks or mismatches `_schema_version`."""
    try:
        payload = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        # Unreadable/corrupt files are treated as incompatible — they cannot
        # be resumed anyway and likely should also be archived.
        return True
    if not isinstance(payload, dict):
        return True
    return payload.get("_schema_version") != current_version


def cleanup_state(
    *,
    pipeline_runs_dir: Path,
    confirm: bool = False,
    purge: bool = False,
) -> CleanupSummary:
    """Walk `pipeline_runs_dir` and archive/purge incompatible state files.

    Args:
        pipeline_runs_dir: Path to the `.pipeline_runs/` root.
        confirm: When False (default), only report; take no action.
        purge: When True (with confirm), `rm` instead of moving to archive.

    Returns:
        Populated `CleanupSummary`.
    """
    from academic_pipeline.pipeline.state import PIPELINE_STATE_SCHEMA_VERSION

    summary = CleanupSummary()
    if not pipeline_runs_dir.is_dir():
        return summary

    archive_root = pipeline_runs_dir / "_archive"

    candidates = [
        p
        for p in pipeline_runs_dir.glob("*.json")
        # Skip anything inside _archive/ — already cleaned (idempotency).
        if archive_root not in p.parents
    ]
    incompatible = [p for p in candidates if _is_incompatible(p, PIPELINE_STATE_SCHEMA_VERSION)]
    summary.incompatible_count = len(incompatible)
    summary.incompatible_files = list(incompatible)

    if not confirm:
        return summary

    if purge:
        for path in incompatible:
            path.unlink()
            summary.purged_count += 1
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        target_dir = archive_root / ts
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in incompatible:
            shutil.move(str(path), str(target_dir / path.name))
            summary.archived_count += 1

    return summary


def _format_report(summary: CleanupSummary, *, confirmed: bool, purged: bool) -> str:
    """Render a human-readable single-line summary for stderr/CLI output."""
    if summary.incompatible_count == 0:
        return "cleanup-state: no incompatible state files found"
    if not confirmed:
        files = ", ".join(p.name for p in summary.incompatible_files)
        return (
            f"cleanup-state DRY-RUN: would archive {summary.incompatible_count} "
            f"file(s): {files}. Re-run with --confirm to apply."
        )
    if purged:
        return f"cleanup-state: purged {summary.purged_count} incompatible file(s)"
    return f"cleanup-state: archived {summary.archived_count} incompatible file(s) to _archive/"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `python tools/cleanup_state.py [...]`."""
    parser = argparse.ArgumentParser(
        prog="cleanup_state",
        description="Archive/purge incompatible PipelineState files (PRD §6.9.T5).",
    )
    parser.add_argument(
        "--pipeline-runs-dir",
        default=".pipeline_runs",
        help="Path to the .pipeline_runs/ root (default: .pipeline_runs).",
    )
    parser.add_argument(
        "--before",
        default="2.5.0",
        help="Version cutoff label (informational; current scope is v2.4.0 → v2.5.0 only per PRD OQ17).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Take action. Without this flag the script is a dry-run (safe default).",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete incompatible files outright instead of archiving (default: archive).",
    )
    args = parser.parse_args(argv)

    summary = cleanup_state(
        pipeline_runs_dir=Path(args.pipeline_runs_dir),
        confirm=args.confirm,
        purge=args.purge,
    )
    print(_format_report(summary, confirmed=args.confirm, purged=args.purge), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
