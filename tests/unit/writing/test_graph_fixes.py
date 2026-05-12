"""Tests for writing-graph node fixes (abstract truncation + author config + figures)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from academic_pipeline.models.shared import Author
from academic_pipeline.models.writing import (
    PaperDraft,
    Section,
)
from academic_pipeline.writing.state import WritingState


def _draft_with_long_first_section() -> PaperDraft:
    """A draft whose first section's content is >500 chars and contains
    a `**Bold**` token starting near the 500-char mark — the historical
    truncation produces `**Ob` (open bold marker) at the cut point."""
    long_content = (
        "**Background.** " + "x" * 480 + " **Objectives.** more text here that should not be cut."
    )
    return PaperDraft(
        title="t",
        abstract="",
        authors=[Author(name="a", affiliation="b")],
        keywords=["k1", "k2", "k3"],
        sections=[
            Section(heading="Body", level=1, content=long_content, word_count=10, citation_count=0)
        ],
        references=[],
        total_word_count=10,
    )


@pytest.mark.asyncio
async def test_section_merger_does_not_truncate_mid_token() -> None:
    """SectionMergerNode must NOT synthesise an abstract from sections[0]
    by character truncation — it produces dangling-bold artifacts.
    Abstract is left empty here; the dedicated abstract agent fills it later."""
    from academic_pipeline.writing.graph import SectionMergerNode

    state = WritingState(topic="t")
    state.section_drafts = _draft_with_long_first_section().sections
    state.paper_outline = None
    state.bibliography = None

    ctx = MagicMock()
    ctx.state = state

    await SectionMergerNode().run(ctx)

    assert state.paper_draft is not None
    # Abstract is empty placeholder, NOT a truncated section.
    assert state.paper_draft.abstract == ""
    # And specifically, no dangling-bold artifact present.
    assert "**Ob" not in state.paper_draft.abstract


@pytest.mark.asyncio
async def test_merge_phase5_writes_real_abstract_back_via_model_copy() -> None:
    """MergePhase5Node must persist the dedicated abstract agent's output
    back into the draft. PaperDraft is frozen — must use model_copy."""
    from academic_pipeline.writing.graph import MergePhase5Node

    state = WritingState(topic="t")
    state.paper_draft = _draft_with_long_first_section().model_copy(update={"abstract": ""})
    state.abstract_result = {"abstract_text": "Real abstract from agent. Complete sentence."}
    state.figure_package = None

    ctx = MagicMock()
    ctx.state = state

    await MergePhase5Node().run(ctx)

    assert state.paper_draft is not None
    assert state.paper_draft.abstract == "Real abstract from agent. Complete sentence."
    assert "**Ob" not in state.paper_draft.abstract


@pytest.mark.asyncio
async def test_merge_phase5_handles_missing_abstract_text() -> None:
    """If abstract_result has no abstract_text, leave the draft abstract as-is."""
    from academic_pipeline.writing.graph import MergePhase5Node

    state = WritingState(topic="t")
    initial = _draft_with_long_first_section().model_copy(update={"abstract": "preset"})
    state.paper_draft = initial
    state.abstract_result = {}
    state.figure_package = None

    ctx = MagicMock()
    ctx.state = state

    await MergePhase5Node().run(ctx)

    # No clobbering when abstract_text is absent
    assert state.paper_draft is not None
    assert state.paper_draft.abstract == "preset"


@pytest.mark.asyncio
async def test_merge_phase5_uses_model_copy_not_mutation() -> None:
    """PaperDraft is frozen — direct attribute assignment would raise.
    Verifies the implementation uses model_copy."""
    from academic_pipeline.writing.graph import MergePhase5Node

    state = WritingState(topic="t")
    initial = _draft_with_long_first_section().model_copy(update={"abstract": ""})
    state.paper_draft = initial
    state.abstract_result = {"abstract_text": "New abstract."}
    state.figure_package = None

    ctx = MagicMock()
    ctx.state = state

    await MergePhase5Node().run(ctx)

    # Must produce a NEW object, not mutate (frozen models can't be mutated)
    assert state.paper_draft is not None
    assert state.paper_draft is not initial  # new instance
    assert state.paper_draft.abstract == "New abstract."
    # Other fields preserved
    assert state.paper_draft.title == initial.title


@pytest.mark.asyncio
async def test_section_merger_reads_authors_from_typed_paper_config() -> None:
    """SectionMergerNode reads authors from PaperConfig (typed) instead of hardcoded."""
    from academic_pipeline.models.shared import Author
    from academic_pipeline.models.writing import PaperConfig
    from academic_pipeline.writing.graph import SectionMergerNode

    state = WritingState(topic="t")
    state.section_drafts = [
        Section(heading="Body", level=1, content="x", word_count=1, citation_count=0)
    ]
    state.paper_outline = None
    state.bibliography = None
    state.paper_config = PaperConfig(
        topic="t",
        research_question="rq",
        paper_type="IMRaD",
        discipline="cs",
        target_journal="JMLR",
        citation_format="APA7",
        word_count_target=8000,
        writing_task="full-paper",
        authors=[
            Author(name="Jackson Yang", affiliation="Example Institute", email="jackson@example.com"),
        ],
    )

    ctx = MagicMock()
    ctx.state = state

    await SectionMergerNode().run(ctx)

    assert state.paper_draft is not None
    assert len(state.paper_draft.authors) == 1
    assert state.paper_draft.authors[0].name == "Jackson Yang"
    assert state.paper_draft.authors[0].affiliation == "Example Institute"
    assert state.paper_draft.authors[0].email == "jackson@example.com"


@pytest.mark.asyncio
async def test_section_merger_default_when_paper_config_none() -> None:
    """When paper_config is None, default authors must NOT be the obviously-broken placeholder."""
    from academic_pipeline.writing.graph import SectionMergerNode

    state = WritingState(topic="t")
    state.section_drafts = [
        Section(heading="Body", level=1, content="x", word_count=1, citation_count=0)
    ]
    state.paper_outline = None
    state.bibliography = None
    state.paper_config = None

    ctx = MagicMock()
    ctx.state = state

    await SectionMergerNode().run(ctx)

    assert state.paper_draft is not None
    # Defaults must NOT be the broken placeholder text
    assert state.paper_draft.authors[0].name != "Author"
    assert state.paper_draft.authors[0].affiliation != "Institution"


@pytest.mark.asyncio
async def test_section_merger_default_when_paper_config_has_no_authors() -> None:
    """When paper_config exists but authors=[], fall back to non-broken default."""
    from academic_pipeline.models.writing import PaperConfig
    from academic_pipeline.writing.graph import SectionMergerNode

    state = WritingState(topic="t")
    state.section_drafts = [
        Section(heading="Body", level=1, content="x", word_count=1, citation_count=0)
    ]
    state.paper_outline = None
    state.bibliography = None
    state.paper_config = PaperConfig(
        topic="t", research_question="rq", paper_type="IMRaD",
        discipline="cs", target_journal="JMLR", citation_format="APA7",
        word_count_target=8000, writing_task="full-paper",
        authors=[],
    )

    ctx = MagicMock()
    ctx.state = state

    await SectionMergerNode().run(ctx)

    assert state.paper_draft is not None
    assert state.paper_draft.authors[0].name != "Author"
    assert state.paper_draft.authors[0].affiliation != "Institution"
