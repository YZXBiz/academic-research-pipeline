"""Tests for AgentMessageCache with PydanticAI-native serialization."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from academic_pipeline.tools.agent_cache import AgentMessageCache


def _sample_messages() -> list[ModelRequest | ModelResponse]:
    return [
        ModelRequest(parts=[UserPromptPart(content="Run experiment")]),
        ModelResponse(parts=[TextPart(content="Starting AutoGluon training...")]),
        ModelRequest(parts=[UserPromptPart(content="Check results")]),
        ModelResponse(parts=[TextPart(content="Accuracy: 0.87")]),
    ]


def test_save_and_load_round_trips(tmp_path: Path) -> None:
    cache = AgentMessageCache(cache_dir=str(tmp_path), agent_name="ml_engineer")
    messages = _sample_messages()
    messages_json = ModelMessagesTypeAdapter.dump_json(messages)

    cache.save(messages_json)
    loaded = cache.load()

    assert loaded is not None
    assert len(loaded) == 4
    assert isinstance(loaded[0], ModelRequest)
    assert isinstance(loaded[1], ModelResponse)


def test_load_returns_none_when_no_cache(tmp_path: Path) -> None:
    cache = AgentMessageCache(cache_dir=str(tmp_path), agent_name="ml_engineer")
    assert cache.load() is None
    assert not cache.exists()


def test_load_returns_none_on_corrupt_cache(tmp_path: Path) -> None:
    cache = AgentMessageCache(cache_dir=str(tmp_path), agent_name="ml_engineer")
    cache.cache_path.write_text("not valid json {{{")
    assert cache.load() is None


def test_exists_and_clear(tmp_path: Path) -> None:
    cache = AgentMessageCache(cache_dir=str(tmp_path), agent_name="ml_engineer")
    messages = _sample_messages()
    messages_json = ModelMessagesTypeAdapter.dump_json(messages)

    assert not cache.exists()
    cache.save(messages_json)
    assert cache.exists()
    cache.clear()
    assert not cache.exists()


# PRD §6.9.T2 — for_agent(thread_id, agent_name) classmethod sugar.


def test_for_agent_classmethod_returns_cache_at_per_thread_dir(tmp_path: Path, monkeypatch) -> None:
    """`AgentMessageCache.for_agent('t-1', 'draft_writer')` resolves to .pipeline_runs/t-1/draft_writer.json."""
    monkeypatch.chdir(tmp_path)

    cache = AgentMessageCache.for_agent(thread_id="t-1", agent_name="draft_writer")

    assert isinstance(cache, AgentMessageCache)
    # cache_dir is stored as a relative path; resolve against cwd to compare absolute.
    expected_dir = tmp_path / ".pipeline_runs" / "t-1"
    assert cache.cache_dir.resolve() == expected_dir.resolve()
    assert cache.cache_path.resolve() == (expected_dir / "draft_writer.json").resolve()
    # Sanity: the directory was created (constructor ensures it exists).
    assert expected_dir.is_dir()


def test_for_agent_isolates_caches_across_agents_within_same_thread(tmp_path: Path, monkeypatch) -> None:
    """Two for_agent() calls with different agent_names yield disjoint cache files."""
    monkeypatch.chdir(tmp_path)

    a = AgentMessageCache.for_agent(thread_id="t-2", agent_name="draft_writer")
    b = AgentMessageCache.for_agent(thread_id="t-2", agent_name="config_writer")

    assert a.cache_path != b.cache_path
    assert a.cache_dir == b.cache_dir  # same per-thread dir
    a.save(b'[{"kind": "request", "parts": []}]')
    assert a.exists()
    assert not b.exists()


def test_for_agent_isolates_caches_across_threads_for_same_agent(tmp_path: Path, monkeypatch) -> None:
    """Two for_agent() calls with different thread_ids yield disjoint cache dirs."""
    monkeypatch.chdir(tmp_path)

    a = AgentMessageCache.for_agent(thread_id="t-A", agent_name="draft_writer")
    b = AgentMessageCache.for_agent(thread_id="t-B", agent_name="draft_writer")

    assert a.cache_dir != b.cache_dir
    assert a.cache_path != b.cache_path
