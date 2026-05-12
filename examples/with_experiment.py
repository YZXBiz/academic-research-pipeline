"""Pipeline with --force-experiment, mocked agents.

Demonstrates the experiment subgraph: design → InteractiveML → judge → analyze.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from academic_pipeline.sdk.pipeline import Pipeline
from examples._helpers import override_all_agents


async def main() -> int:
    pipeline = Pipeline(
        topic="Effect of prompt length on LLM hallucination rates",
        thread_id="example-experiment",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
    )
    pipeline._deps.config.force_experiment = True

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    print(f"Run finished. Status: {pipeline._run_state.pipeline_status}")
    if "experiment" in pipeline._run_state.stages:
        nodes = pipeline._run_state.stages["experiment"].nodes
        print(f"Experiment nodes ran: {[n.name for n in nodes]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
