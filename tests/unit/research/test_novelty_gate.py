"""Tests for compute_novelty_gate (SCI Spec 3 Phase 1)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from academic_pipeline.models.novelty_gate import NoveltyGateResult
from academic_pipeline.research.novelty_gate import compute_novelty_gate


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _s2_payload(matches: list[dict]) -> str:
    """Build a JSON string in the shape returned by search_s2_by_title."""
    return json.dumps({"query": "test topic", "matches": matches})


@asynccontextmanager
async def _patched_search(payload: str | Exception) -> AsyncIterator[None]:
    """Patch search_s2_by_title to return payload (or raise if exception)."""
    target = "academic_pipeline.research.novelty_gate.search_s2_by_title"
    if isinstance(payload, Exception):
        with patch(target, new=AsyncMock(side_effect=payload)):
            yield
    else:
        with patch(target, new=AsyncMock(return_value=payload)):
            yield


@pytest.mark.asyncio
async def test_compute_novelty_gate_returns_redundant_on_high_similarity():
    """Max similarity >= tau_block must yield REDUNDANT verdict."""
    topic = "Foundation Models for Time Series Forecasting"
    payload = _s2_payload([
        {
            "paperId": "abc123",
            "title": "Foundation Models for Time Series Forecasting",  # identical
            "doi": "10.1000/xyz",
            "similarity": 1.0,
            "abstract": "We present a foundation model for time series.",
        },
    ])
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic, tau_warn=0.78, tau_block=0.92, top_n=10)

    assert isinstance(result, NoveltyGateResult)
    assert result.verdict == "redundant"
    assert result.max_similarity >= 0.92
    assert len(result.nearest_neighbors) == 1
    assert result.nearest_neighbors[0].title == "Foundation Models for Time Series Forecasting"
    assert "REDUNDANT" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_returns_novel_on_low_similarity():
    """Max similarity below tau_warn must yield NOVEL verdict."""
    topic = "Quantum entanglement teleportation across galactic distances"
    payload = _s2_payload([
        {
            "paperId": "def456",
            "title": "A study of medieval Belgian poetry forms",  # very different
            "doi": "10.1000/poem",
            "similarity": 0.10,
            "abstract": "On the prosody of 14th-century Flemish verse.",
        },
    ])
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic, tau_warn=0.78, tau_block=0.92, top_n=10)

    assert result.verdict == "novel"
    assert result.max_similarity < 0.78
    assert "NOVEL" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_returns_partial_on_mid_similarity():
    """Max similarity between tau_warn and tau_block must yield PARTIAL verdict."""
    topic = "topic"
    payload = _s2_payload([
        {
            "paperId": "ghi789",
            "title": "near match",
            "doi": "10.1000/abc",
            "similarity": 0.85,
            "abstract": "abstract text",
        },
    ])
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic, tau_warn=0.78, tau_block=0.92, top_n=10)

    assert result.verdict == "partial"
    assert 0.78 <= result.max_similarity < 0.92
    assert "PARTIAL" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_returns_novel_on_api_error():
    """When S2 search raises an exception, gate must degrade gracefully to NOVEL."""
    topic = "anything"
    async with _patched_search(RuntimeError("S2 unreachable: timeout")):
        result = await compute_novelty_gate(topic)

    assert result.verdict == "novel"
    assert result.max_similarity == 0.0
    assert result.nearest_neighbors == []
    assert "S2 unreachable" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_returns_novel_on_empty_results():
    """No matches from S2 → NOVEL verdict, empty neighbors."""
    topic = "any topic"
    payload = _s2_payload([])
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic)

    assert result.verdict == "novel"
    assert result.max_similarity == 0.0
    assert result.nearest_neighbors == []
    assert "No similar papers" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_handles_degraded_s2_payload():
    """When search_s2_by_title returns degraded=True, gate degrades to NOVEL."""
    topic = "any"
    payload = json.dumps({"degraded": True, "error": "rate limited", "query": topic})
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic)

    assert result.verdict == "novel"
    assert "rate limited" in result.note


@pytest.mark.asyncio
async def test_compute_novelty_gate_caps_neighbors_at_top_n():
    """Only top_n neighbors retained; sorted by similarity desc."""
    topic = "machine learning"
    matches = [
        {"paperId": f"id{i}", "title": f"paper {i}", "similarity": 0.5 + i * 0.01, "doi": ""}
        for i in range(20)
    ]
    payload = _s2_payload(matches)
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic, tau_warn=0.78, tau_block=0.92, top_n=5)

    assert len(result.nearest_neighbors) == 5
    # Sorted descending by similarity
    sims = [n.similarity for n in result.nearest_neighbors]
    assert sims == sorted(sims, reverse=True)


@pytest.mark.asyncio
async def test_compute_novelty_gate_recomputes_similarity_when_missing():
    """When S2 candidate lacks 'similarity', the gate recomputes via difflib."""
    topic = "exact title here"
    payload = _s2_payload([
        {"paperId": "x", "title": "exact title here", "doi": ""},  # no 'similarity' field
    ])
    async with _patched_search(payload):
        result = await compute_novelty_gate(topic, tau_warn=0.78, tau_block=0.92, top_n=10)

    assert result.verdict == "redundant"
    assert result.max_similarity >= 0.92
