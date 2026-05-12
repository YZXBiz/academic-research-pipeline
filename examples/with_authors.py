"""Pipeline with PaperConfig.authors populated — fills the title page properly."""

from __future__ import annotations

import asyncio
from pathlib import Path

from academic_pipeline.models.shared import Author
from academic_pipeline.models.writing import PaperConfig
from academic_pipeline.sdk.pipeline import Pipeline
from examples._helpers import override_all_agents


async def main() -> int:
    paper_config = PaperConfig(
        topic="Multi-agent LLM frameworks: a survey",
        research_question="",
        paper_type="literature_review",
        discipline="Computer Science",
        target_journal="JMLR",
        citation_format="APA7",
        word_count_target=8000,
        writing_task="full-paper",
        authors=[
            Author(name="Jackson Yang", affiliation="Example Institute", email="jackson@example.com"),
            Author(name="Co Author", affiliation="Other Lab"),
        ],
    )

    pipeline = Pipeline(
        topic="Multi-agent LLM frameworks: a survey",
        thread_id="example-authors",
        interactive=False,
        persistence_dir=Path("/tmp/example-pipeline-runs"),
        paper_config=paper_config,
    )

    with override_all_agents():
        async for _ in pipeline.run_stream(output_dir="/tmp/example-output"):
            pass

    draft = pipeline._state.paper_draft
    if draft is not None:
        print(f"Title-page authors: {[a.name for a in draft.authors]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
