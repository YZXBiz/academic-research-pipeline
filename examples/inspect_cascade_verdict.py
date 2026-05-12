"""Pipeline run with cascaded review enabled; inspect state.cascade_result.

Demonstrates Spec 6 Phase 1: the CascadedReviewNode runs after the parallel
reviewers and populates state.cascade_result. The editorial synthesizer reads
it but does not yet enforce the verdict (Phase 2). This example surfaces the
verdict so an SDK consumer can post-process it.

PRD §6.12.T3 + §6.4 (cascaded review).

Run:
    uv run python examples/inspect_cascade_verdict.py            # offline TestModel run
    uv run python examples/inspect_cascade_verdict.py --dry-run  # CI smoke (exits 0)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _is_dry_run() -> bool:
    return "--dry-run" in sys.argv[1:]


async def main() -> int:
    """Run the cascaded-review example (use --dry-run to skip the actual run)."""
    if _is_dry_run():
        print("dry-run OK — skipping full TestModel pipeline run")
        return 0

    from examples._helpers import override_all_agents

    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline(
        topic="Reproducibility of LLM-generated experimental code",
        thread_id="example-cascade",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
    )
    pipeline._deps.config.cascaded_review_enabled = True
    pipeline._deps.config.persona_reviewers_enabled = True

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    cascade = pipeline._state.cascade_result
    if cascade is None:
        print("cascade_result is None — review subgraph did not populate it")
    else:
        print(f"cascade final_verdict: {cascade.final_verdict}")
        if cascade.rejection_stage is not None:
            print(f"  rejected at: {cascade.rejection_stage} — {cascade.rejection_summary[:80]}")
        for sr in cascade.stages:
            print(f"  {sr.stage}: {sr.verdict} ({sr.gate_reason or ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
