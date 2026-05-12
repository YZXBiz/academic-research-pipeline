"""Pipeline run targeting an ACL-style venue (target_journal='ACL').

Demonstrates how to bias the writing subgraph toward conference-paper conventions
(short abstract, IMRaD body, IEEE-style numeric citations) by passing a
PaperConfig with target_journal='ACL'.

PRD §6.12.T3 — also part of the §6.7 rendering-pivot story.

Run:
    uv run python examples/run_with_acl_template.py            # offline TestModel run
    uv run python examples/run_with_acl_template.py --dry-run  # CI smoke (exits 0)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def _is_dry_run() -> bool:
    return "--dry-run" in sys.argv[1:]


async def main() -> int:
    """Run the ACL-template example (use --dry-run to skip the actual run)."""
    if _is_dry_run():
        print("dry-run OK — skipping full TestModel pipeline run")
        return 0

    from examples._helpers import override_all_agents

    from academic_pipeline.models.writing import PaperConfig
    from academic_pipeline.sdk.pipeline import Pipeline

    paper_config = PaperConfig(
        topic="Length-aware decoding for conference-style abstracts",
        research_question="Does length-aware decoding improve abstract quality?",
        paper_type="Conference",
        discipline="Computational Linguistics",
        target_journal="ACL",
        citation_format="IEEE",
        word_count_target=4000,
        writing_task="full-paper",
    )

    pipeline = Pipeline(
        topic=paper_config.topic,
        thread_id="example-acl",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
        paper_config=paper_config,
    )

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    print(f"Run finished. target_journal={paper_config.target_journal}")
    print(f"Stages observed: {list(pipeline._run_state.stages.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
