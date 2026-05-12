"""Minimal Pipeline run with mocked agents — no API key required.

Demonstrates:
- Pipeline construction with a topic
- TestModel override for every agent registry
- Inspecting the resulting state.paper_draft
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from academic_pipeline.sdk.pipeline import Pipeline
from examples._helpers import override_all_agents


async def main() -> int:
    pipeline = Pipeline(
        topic="Impact of LLMs on academic peer review",
        thread_id="example-basic",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
    )

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    print(f"Run finished. Status: {pipeline._run_state.pipeline_status}")
    print(f"Stages observed: {list(pipeline._run_state.stages.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
