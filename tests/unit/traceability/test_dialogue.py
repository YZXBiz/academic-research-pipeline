"""Tests for run_writer_reviewer_dialogue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from academic_pipeline.models.numerical import NumericalStore
from academic_pipeline.traceability.dialogue import (
    DEFAULT_TERMINATION_PHRASE,
    run_writer_reviewer_dialogue,
)


class _FakeOutput:
    def __init__(self, text: str) -> None:
        self.text = text
        self.section_name = "results"


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.output = _FakeOutput(text)

    def all_messages(self) -> list[object]:
        return []


@pytest.mark.asyncio
async def test_dialogue_terminates_on_termination_phrase() -> None:
    writer = MagicMock()
    writer.run = AsyncMock(side_effect=[_FakeResult("Draft one"), _FakeResult("Draft two")])
    reviewer = MagicMock()
    reviewer.run = AsyncMock(return_value=_FakeResult(DEFAULT_TERMINATION_PHRASE))

    final = await run_writer_reviewer_dialogue(
        writer=writer, reviewer=reviewer,
        prompt="Write the results.", deps=None,
        store=NumericalStore(), max_turns=3,
    )
    assert final.output.text == "Draft one"
    assert writer.run.call_count == 1  # terminated after first draft


@pytest.mark.asyncio
async def test_dialogue_loops_on_review_feedback() -> None:
    writer = MagicMock()
    writer.run = AsyncMock(side_effect=[
        _FakeResult("Draft one"), _FakeResult("Draft two"), _FakeResult("Draft three"),
    ])
    reviewer = MagicMock()
    reviewer.run = AsyncMock(side_effect=[
        _FakeResult("Improve X"),
        _FakeResult("Improve Y"),
        _FakeResult(DEFAULT_TERMINATION_PHRASE),
    ])
    final = await run_writer_reviewer_dialogue(
        writer=writer, reviewer=reviewer,
        prompt="Write the results.", deps=None,
        store=NumericalStore(), max_turns=5,
    )
    assert final.output.text == "Draft three"
    assert writer.run.call_count == 3
    assert reviewer.run.call_count == 3


@pytest.mark.asyncio
async def test_dialogue_max_turns_returns_last_draft() -> None:
    writer = MagicMock()
    writer.run = AsyncMock(side_effect=[
        _FakeResult("Draft one"), _FakeResult("Draft two"),
    ])
    reviewer = MagicMock()
    reviewer.run = AsyncMock(return_value=_FakeResult("Still needs work"))
    final = await run_writer_reviewer_dialogue(
        writer=writer, reviewer=reviewer,
        prompt="Write.", deps=None,
        store=NumericalStore(), max_turns=2,
    )
    # Returns the last writer draft even when not terminated
    assert final.output.text == "Draft two"
