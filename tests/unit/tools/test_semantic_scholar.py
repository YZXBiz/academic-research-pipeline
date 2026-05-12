"""Tests for async Semantic Scholar API tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai import ModelRetry

from academic_pipeline.tools.bibliography.semantic_scholar import (
    _title_similarity,
    batch_verify_s2,
    get_s2_paper_details,
    search_s2_by_title,
)


pytestmark = pytest.mark.anyio


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response for mocking."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


# ---------------------------------------------------------------------------
# _title_similarity
# ---------------------------------------------------------------------------


class TestTitleSimilarity:
    """Tests for the _title_similarity helper."""

    def test_exact_match(self) -> None:
        assert _title_similarity("Attention Is All You Need", "Attention Is All You Need") == 1.0

    def test_case_insensitive(self) -> None:
        assert _title_similarity("attention is all you need", "ATTENTION IS ALL YOU NEED") == 1.0

    def test_near_match_above_threshold(self) -> None:
        score = _title_similarity(
            "Attention Is All You Need",
            "Attention Is All We Need",
        )
        assert score >= 0.70

    def test_below_threshold(self) -> None:
        score = _title_similarity(
            "Attention Is All You Need",
            "Completely Different Paper Title About Economics",
        )
        assert score < 0.70

    def test_empty_strings(self) -> None:
        assert _title_similarity("", "") == 1.0

    def test_one_empty(self) -> None:
        assert _title_similarity("Some Title", "") == 0.0


# ---------------------------------------------------------------------------
# search_s2_by_title
# ---------------------------------------------------------------------------


class TestSearchS2ByTitle:
    """Tests for the search_s2_by_title tool function."""

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_success_with_matches(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Attention Is All You Need",
                        "externalIds": {"DOI": "10.5555/3295222.3295349"},
                        "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
                        "year": 2017,
                        "citationCount": 50000,
                    },
                    {
                        "paperId": "def456",
                        "title": "Some Other Paper",
                        "externalIds": {},
                        "authors": [{"name": "Smith"}],
                        "year": 2020,
                        "citationCount": 10,
                    },
                ]
            }
        )
        result = await search_s2_by_title("Attention Is All You Need")
        parsed = json.loads(result)
        assert "matches" in parsed
        assert len(parsed["matches"]) == 2
        assert parsed["matches"][0]["paperId"] == "abc123"
        assert parsed["matches"][0]["similarity"] == 1.0
        assert parsed["matches"][0]["doi"] == "10.5555/3295222.3295349"

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_empty_results(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(json_data={"data": []})
        result = await search_s2_by_title("Nonexistent Paper Title XYZ")
        parsed = json.loads(result)
        assert parsed["matches"] == []

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_network_error_returns_degraded(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = httpx.ConnectError("Connection refused")
        result = await search_s2_by_title("Some Paper")
        parsed = json.loads(result)
        assert parsed["degraded"] is True
        assert "error" in parsed

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_null_data_field(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(json_data={"data": None})
        result = await search_s2_by_title("Test")
        parsed = json.loads(result)
        assert parsed["matches"] == []


# ---------------------------------------------------------------------------
# batch_verify_s2
# ---------------------------------------------------------------------------


class TestBatchVerifyS2:
    """Tests for the batch_verify_s2 tool function."""

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_verified_reference(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Attention Is All You Need",
                        "externalIds": {"DOI": "10.5555/3295222.3295349"},
                        "authors": [],
                        "year": 2017,
                        "citationCount": 50000,
                    }
                ]
            }
        )
        refs = json.dumps(
            [{"title": "Attention Is All You Need", "doi": "10.5555/3295222.3295349", "authors": "", "year": "2017"}]
        )
        result = await batch_verify_s2(refs)
        parsed = json.loads(result)
        assert parsed["results"][0]["verdict"] == "S2_VERIFIED"
        assert parsed["summary"]["verified"] == 1

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_doi_mismatch(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Attention Is All You Need",
                        "externalIds": {"DOI": "10.5555/different.doi"},
                        "authors": [],
                        "year": 2017,
                        "citationCount": 50000,
                    }
                ]
            }
        )
        refs = json.dumps(
            [{"title": "Attention Is All You Need", "doi": "10.5555/3295222.3295349", "authors": "", "year": "2017"}]
        )
        result = await batch_verify_s2(refs)
        parsed = json.loads(result)
        assert parsed["results"][0]["verdict"] == "S2_DOI_MISMATCH"
        assert parsed["summary"]["doi_mismatch"] == 1

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_not_found(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "data": [
                    {
                        "paperId": "xyz",
                        "title": "Completely Different Paper",
                        "externalIds": {},
                        "authors": [],
                        "year": 2020,
                        "citationCount": 5,
                    }
                ]
            }
        )
        refs = json.dumps([{"title": "Attention Is All You Need", "doi": "", "authors": "", "year": "2017"}])
        result = await batch_verify_s2(refs)
        parsed = json.loads(result)
        assert parsed["results"][0]["verdict"] == "S2_NOT_FOUND"
        assert parsed["summary"]["not_found"] == 1

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_degraded_on_api_error(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = httpx.TimeoutException("Timed out")
        refs = json.dumps([{"title": "Some Paper", "doi": "", "authors": "", "year": "2020"}])
        result = await batch_verify_s2(refs)
        parsed = json.loads(result)
        assert parsed["results"][0]["verdict"] == "S2_DEGRADED"
        assert parsed["summary"]["degraded"] == 1

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_duplicate_detection(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Attention Is All You Need",
                        "externalIds": {"DOI": "10.5555/3295222.3295349"},
                        "authors": [],
                        "year": 2017,
                        "citationCount": 50000,
                    }
                ]
            }
        )
        refs = json.dumps(
            [
                {"title": "Attention Is All You Need", "doi": "10.5555/3295222.3295349", "authors": "", "year": "2017"},
                {"title": "Attention Is All You Need", "doi": "10.5555/3295222.3295349", "authors": "", "year": "2017"},
            ]
        )
        result = await batch_verify_s2(refs)
        parsed = json.loads(result)
        assert parsed["results"][1]["is_duplicate"] is True
        assert parsed["results"][1]["duplicate_of_index"] == 0
        assert parsed["summary"]["duplicates"] == 1

    async def test_invalid_json_input(self) -> None:
        with pytest.raises(ModelRetry, match="Invalid JSON input"):
            await batch_verify_s2("not valid json {{{")


# ---------------------------------------------------------------------------
# get_s2_paper_details
# ---------------------------------------------------------------------------


class TestGetS2PaperDetails:
    """Tests for the get_s2_paper_details tool function."""

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_success(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "paperId": "abc123",
                "title": "Attention Is All You Need",
                "authors": [{"name": "Vaswani"}, {"name": "Shazeer"}],
                "year": 2017,
                "externalIds": {"DOI": "10.5555/3295222.3295349"},
                "abstract": "The dominant sequence transduction models...",
                "citationCount": 50000,
                "referenceCount": 40,
                "venue": "NeurIPS",
            }
        )
        result = await get_s2_paper_details("abc123")
        parsed = json.loads(result)
        assert parsed["paperId"] == "abc123"
        assert parsed["title"] == "Attention Is All You Need"
        assert len(parsed["authors"]) == 2
        assert parsed["year"] == 2017
        assert parsed["doi"] == "10.5555/3295222.3295349"
        assert parsed["venue"] == "NeurIPS"
        assert parsed["citationCount"] == 50000
        assert parsed["referenceCount"] == 40

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_degraded_on_network_error(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = OSError("DNS resolution failed")
        result = await get_s2_paper_details("abc123")
        parsed = json.loads(result)
        assert parsed["degraded"] is True
        assert "error" in parsed
        assert parsed["paper_id"] == "abc123"

    @patch("academic_pipeline.tools.bibliography.semantic_scholar._s2_fetch")
    async def test_missing_optional_fields(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "paperId": "minimal",
                "title": "Minimal Paper",
            }
        )
        result = await get_s2_paper_details("minimal")
        parsed = json.loads(result)
        assert parsed["paperId"] == "minimal"
        assert parsed["title"] == "Minimal Paper"
        assert parsed["authors"] == []
        assert parsed["year"] is None
        assert parsed["doi"] == ""
        assert parsed["abstract"] == ""
