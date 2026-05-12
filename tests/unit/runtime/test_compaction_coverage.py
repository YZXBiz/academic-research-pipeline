"""Tests that heavy-context agents have AnthropicCompaction."""
from __future__ import annotations

from pydantic_ai.models.anthropic import AnthropicCompaction


def _has_compaction(agent) -> bool:
    """Check whether an agent's capability tree contains AnthropicCompaction."""
    rc = agent._root_capability
    if isinstance(rc, AnthropicCompaction):
        return True
    caps = getattr(rc, "capabilities", [])
    return any(isinstance(c, AnthropicCompaction) for c in caps)


def test_synthesis_has_compaction():
    from academic_pipeline.research.agents import agents
    assert _has_compaction(agents["synthesis"])


def test_report_compiler_has_compaction():
    from academic_pipeline.research.agents import agents
    assert _has_compaction(agents["report_compiler"])


def test_editor_in_chief_has_compaction():
    from academic_pipeline.research.agents import agents
    assert _has_compaction(agents["editor_in_chief"])


def test_draft_writer_has_compaction():
    from academic_pipeline.writing.agents import agents
    assert _has_compaction(agents["draft_writer"])


def test_citation_compliance_has_compaction():
    from academic_pipeline.writing.agents import agents
    assert _has_compaction(agents["citation_compliance"])


def test_formatter_has_compaction():
    from academic_pipeline.writing.agents import agents
    assert _has_compaction(agents["formatter"])


def test_editorial_synthesizer_has_compaction():
    from academic_pipeline.review.agents import agents
    assert _has_compaction(agents["editorial_synthesizer"])
