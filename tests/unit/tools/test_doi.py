"""Tests for async DOI verification tools (PydanticAI-compatible)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai import ModelRetry

from academic_pipeline.tools.bibliography.doi import (
    check_retraction,
    resolve_doi_metadata,
    verify_doi,
)


pytestmark = pytest.mark.anyio


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response for mocking."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = httpx.Headers(headers or {})
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    return resp


class TestVerifyDoi:
    """Tests for the verify_doi async tool."""

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_valid_doi_resolves(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            status_code=302,
            headers={"location": "https://journals.example.com/article/123"},
        )
        result = await verify_doi("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["exists"] is True
        assert parsed["doi"] == "10.1234/test.doi"
        assert parsed["status"] == 302

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_invalid_doi_returns_not_found(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(status_code=404)
        result = await verify_doi("10.1234/nonexistent")
        parsed = json.loads(result)
        assert parsed["exists"] is False
        assert "not found" in parsed["error"].lower()

    async def test_malformed_doi_format(self) -> None:
        with pytest.raises(ModelRetry, match="Invalid DOI format"):
            await verify_doi("not-a-doi")

    async def test_empty_doi(self) -> None:
        with pytest.raises(ModelRetry, match="Invalid DOI format"):
            await verify_doi("")

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_network_error_handled(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = httpx.ConnectError("Connection refused")
        result = await verify_doi("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["exists"] is False
        assert "error" in parsed

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_strips_url_prefix(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(status_code=200)
        result = await verify_doi("https://doi.org/10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["doi"] == "10.1234/test.doi"


class TestCheckRetraction:
    """Tests for the check_retraction async tool."""

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_not_retracted(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "message": {
                    "title": ["Test Paper"],
                    "type": "journal-article",
                    "update-to": [],
                }
            }
        )
        result = await check_retraction("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["retracted"] is False
        assert parsed["title"] == "Test Paper"

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_retracted_paper(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "message": {
                    "update-to": [
                        {
                            "type": "retraction",
                            "DOI": "10.1234/retraction",
                            "updated": {"date-parts": [[2024, 1, 15]]},
                        }
                    ]
                }
            }
        )
        result = await check_retraction("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["retracted"] is True
        assert parsed["retraction_doi"] == "10.1234/retraction"

    async def test_invalid_doi_format(self) -> None:
        with pytest.raises(ModelRetry, match="Invalid DOI format"):
            await check_retraction("bad-doi")

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_doi_not_in_crossref(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(status_code=404)
        result = await check_retraction("10.1234/unknown")
        parsed = json.loads(result)
        assert parsed["retracted"] == "unknown"
        assert "not found" in parsed["reason"].lower()

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_network_error_handled(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = httpx.TimeoutException("Timed out")
        result = await check_retraction("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["retracted"] == "unknown"
        assert "error" in parsed


class TestResolveDOIMetadata:
    """Tests for the resolve_doi_metadata async tool."""

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_resolves_full_metadata(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "message": {
                    "title": ["Deep Learning in NLP"],
                    "author": [
                        {"family": "Smith", "given": "John"},
                        {"family": "Doe", "given": "Jane"},
                    ],
                    "published-print": {"date-parts": [[2023]]},
                    "container-title": ["Nature ML"],
                    "volume": "5",
                    "issue": "2",
                    "page": "100-115",
                    "type": "journal-article",
                    "publisher": "Nature Publishing",
                    "ISSN": ["1234-5678"],
                    "URL": "https://example.com/paper",
                }
            }
        )
        result = await resolve_doi_metadata("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["found"] is True
        assert parsed["title"] == "Deep Learning in NLP"
        assert len(parsed["authors"]) == 2
        assert parsed["year"] == 2023
        assert parsed["journal"] == "Nature ML"
        assert parsed["volume"] == "5"

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_doi_not_found(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(status_code=404)
        result = await resolve_doi_metadata("10.1234/missing")
        parsed = json.loads(result)
        assert parsed["found"] is False
        assert "not in crossref" in parsed["error"].lower()

    async def test_invalid_doi_format(self) -> None:
        with pytest.raises(ModelRetry, match="Invalid DOI format"):
            await resolve_doi_metadata("invalid")

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_network_error_handled(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.side_effect = OSError("DNS resolution failed")
        result = await resolve_doi_metadata("10.1234/test.doi")
        parsed = json.loads(result)
        assert parsed["found"] is False
        assert "error" in parsed

    @patch("academic_pipeline.tools.bibliography.doi._async_fetch")
    async def test_missing_optional_fields(self, mock_fetch: AsyncMock) -> None:
        mock_fetch.return_value = _make_response(
            json_data={
                "message": {
                    "title": ["Minimal Paper"],
                    "type": "journal-article",
                }
            }
        )
        result = await resolve_doi_metadata("10.1234/minimal")
        parsed = json.loads(result)
        assert parsed["found"] is True
        assert parsed["title"] == "Minimal Paper"
        assert parsed["authors"] == []
        assert parsed["year"] is None
