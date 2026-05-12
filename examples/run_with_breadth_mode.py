"""Pipeline run with exploration-breadth bundling (Spec 7) enabled.

Demonstrates how to opt into N-design experiment bundling: the experiment
designer proposes `n_design_alternatives` candidate experiments, the bundle
scorer ranks them, and the top `k_designs_to_run` are selected. In Phase 1
only the highest-scoring design actually runs (no fan-out yet); Phase 2 will
parallelize K runs.

PRD §6.12.T3 + §6.2 (exploration breadth).

Run:
    uv run python examples/run_with_breadth_mode.py            # offline TestModel run
    uv run python examples/run_with_breadth_mode.py --dry-run  # CI smoke (exits 0)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _is_dry_run() -> bool:
    return "--dry-run" in sys.argv[1:]


async def main() -> int:
    """Run the exploration-breadth example (use --dry-run to skip the actual run)."""
    if _is_dry_run():
        print("dry-run OK — skipping full TestModel pipeline run")
        return 0

    from examples._helpers import override_all_agents

    from academic_pipeline.sdk.pipeline import Pipeline

    pipeline = Pipeline(
        topic="Sample-efficiency of fine-tuning vs few-shot for tabular tasks",
        thread_id="example-breadth",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
    )
    # Opt in to exploration-breadth bundling (Spec 7 Phase 1).
    pipeline._deps.config.exploration_breadth_enabled = True
    pipeline._deps.config.n_design_alternatives = 4
    pipeline._deps.config.k_designs_to_run = 1
    pipeline._deps.config.force_experiment = True

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    print(
        f"Run finished. breadth_enabled={pipeline._deps.config.exploration_breadth_enabled} "
        f"N={pipeline._deps.config.n_design_alternatives} "
        f"K={pipeline._deps.config.k_designs_to_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
