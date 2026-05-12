"""Async Semantic Scholar API tools for PydanticAI agents.

Search papers by title, batch-verify references against the S2 corpus,
and retrieve detailed paper metadata via the Semantic Scholar Graph API.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import urllib.parse

import httpx
from pydantic_ai import ModelRetry

from academic_pipeline.config import DEFAULT_CONFIG


logger = logging.getLogger(__name__)

_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_SIMILARITY_THRESHOLD = 0.70

# Rate-limit semaphore: 1 concurrent request at a time, per event loop.
_s2_semaphore_loop: asyncio.AbstractEventLoop | None = None
_s2_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the rate-limit semaphore for the current event loop."""
    global _s2_semaphore, _s2_semaphore_loop
    loop = asyncio.get_running_loop()
    if _s2_semaphore is None or _s2_semaphore_loop is not loop:
        _s2_semaphore = asyncio.Semaphore(1)
        _s2_semaphore_loop = loop
    return _s2_semaphore


ASYNC_NETWORK_ERRORS = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.ConnectError,
    OSError,
    ValueError,
)

def _title_similarity(a: str, b: str) -> float:
    """Compute Levenshtein-style similarity between two title strings."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


async def _s2_fetch(url: str) -> httpx.Response:
    """Perform a rate-limited async GET against the Semantic Scholar API.

    Uses a semaphore to serialise requests and an inter-request delay: 0.1 s when an S2 API key is configured, 1.0 s
    otherwise.
    """
    headers: dict[str, str] = {"User-Agent": "AcademicPipeline/1.0"}

    api_key = DEFAULT_CONFIG.s2_api_key.get_secret_value()  # type: ignore[union-attr]
    if api_key:
        headers["x-api-key"] = api_key

    delay = 0.1 if api_key else 1.0

    async with _get_semaphore():
        async with httpx.AsyncClient(
            verify=DEFAULT_CONFIG.ssl_verify,
            timeout=DEFAULT_CONFIG.http_timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        await asyncio.sleep(delay)
    return response

async def search_s2_by_title(title: str) -> str:
    """Search Semantic Scholar for papers matching a title string.

    Args:
        title: The paper title to search for.

    Returns:
        JSON string with a list of matches, each containing paperId, title,
        doi, and similarity score. Returns degraded status on API failure.
    """
    encoded = urllib.parse.quote(title, safe="")
    url = f"{_S2_BASE}/search?query={encoded}&limit=5&fields=title,externalIds,authors,year,citationCount"
    try:
        resp = await _s2_fetch(url)
        data = resp.json()
    except ASYNC_NETWORK_ERRORS as e:
        logger.warning("S2 title search failed for %r: %s", title, e)
        return json.dumps({"degraded": True, "error": str(e), "query": title})

    papers = data.get("data") or []
    matches: list[dict[str, object]] = []
    for paper in papers:
        paper_title = paper.get("title", "")
        sim = _title_similarity(title, paper_title)
        external_ids = paper.get("externalIds") or {}
        matches.append(
            {
                "paperId": paper.get("paperId", ""),
                "title": paper_title,
                "doi": external_ids.get("DOI", ""),
                "similarity": round(sim, 4),
                "year": paper.get("year"),
                "citationCount": paper.get("citationCount"),
                "authors": [a.get("name", "") for a in (paper.get("authors") or [])],
            }
        )
    return json.dumps({"query": title, "matches": matches})


async def batch_verify_s2(references_json: str) -> str:
    """Batch-verify a list of references against the Semantic Scholar corpus.

    Args:
        references_json: JSON string — an array of objects, each with ``title``, ``doi``, ``authors``, and ``year``
            fields.

    Returns:
        JSON string with per-reference verdicts and a summary. Possible
        verdicts: S2_VERIFIED, S2_DOI_MISMATCH, S2_NOT_FOUND, S2_DEGRADED.
    """
    try:
        references: list[dict[str, str]] = json.loads(references_json)
    except (json.JSONDecodeError, TypeError) as e:
        raise ModelRetry(
            f"Invalid JSON input: {e}. "
            'Provide a JSON array of objects, each with "title", "doi", "authors", and "year" fields.'
        ) from e

    results: list[dict[str, object]] = []
    seen_corpus_ids: dict[str, int] = {}
    counts = {"verified": 0, "doi_mismatch": 0, "not_found": 0, "degraded": 0, "duplicates": 0}

    for idx, ref in enumerate(references):
        ref_title = ref.get("title", "")
        ref_doi = ref.get("doi", "")
        entry: dict[str, object] = {"index": idx, "title": ref_title}

        search_result_str = await search_s2_by_title(ref_title)
        search_result = json.loads(search_result_str)

        if search_result.get("degraded"):
            entry["verdict"] = "S2_DEGRADED"
            entry["error"] = search_result.get("error", "")
            counts["degraded"] += 1
            results.append(entry)
            continue

        matches = search_result.get("matches", [])
        best_match: dict[str, object] | None = None
        best_sim = 0.0
        for m in matches:
            sim = float(m.get("similarity", 0))
            if sim > best_sim:
                best_sim = sim
                best_match = m

        if best_match is None or best_sim < _SIMILARITY_THRESHOLD:
            entry["verdict"] = "S2_NOT_FOUND"
            entry["best_similarity"] = round(best_sim, 4)
            counts["not_found"] += 1
            results.append(entry)
            continue

        # Dedup check via S2 corpus ID (paperId)
        s2_id = str(best_match.get("paperId", ""))
        is_duplicate = False
        if s2_id and s2_id in seen_corpus_ids:
            is_duplicate = True
            counts["duplicates"] += 1
            entry["duplicate_of_index"] = seen_corpus_ids[s2_id]
        if s2_id:
            seen_corpus_ids[s2_id] = idx

        s2_doi = str(best_match.get("doi", ""))
        # DOI comparison (normalised, case-insensitive)
        if ref_doi and s2_doi and ref_doi.lower().strip() != s2_doi.lower().strip():
            entry["verdict"] = "S2_DOI_MISMATCH"
            entry["ref_doi"] = ref_doi
            entry["s2_doi"] = s2_doi
            counts["doi_mismatch"] += 1
        else:
            entry["verdict"] = "S2_VERIFIED"
            counts["verified"] += 1

        entry["s2_paper_id"] = s2_id
        entry["similarity"] = round(best_sim, 4)
        entry["is_duplicate"] = is_duplicate
        results.append(entry)

    return json.dumps({"results": results, "summary": counts})


async def get_s2_paper_details(paper_id: str) -> str:
    """Retrieve detailed metadata for a single paper from Semantic Scholar.

    Args:
        paper_id: The Semantic Scholar paper ID (corpus ID or DOI).

    Returns:
        JSON string with title, authors, year, abstract, citation counts,
        venue, and external IDs. Returns degraded status on API failure.
    """
    fields = "title,authors,year,externalIds,abstract,citationCount,referenceCount,venue"
    url = f"{_S2_BASE}/{urllib.parse.quote(paper_id, safe='')}?fields={fields}"
    try:
        resp = await _s2_fetch(url)
        data = resp.json()
    except ASYNC_NETWORK_ERRORS as e:
        logger.warning("S2 paper details failed for %r: %s", paper_id, e)
        return json.dumps({"degraded": True, "error": str(e), "paper_id": paper_id})

    external_ids = data.get("externalIds") or {}
    return json.dumps(
        {
            "paperId": data.get("paperId", ""),
            "title": data.get("title", ""),
            "authors": [a.get("name", "") for a in (data.get("authors") or [])],
            "year": data.get("year"),
            "doi": external_ids.get("DOI", ""),
            "abstract": data.get("abstract", ""),
            "citationCount": data.get("citationCount"),
            "referenceCount": data.get("referenceCount"),
            "venue": data.get("venue", ""),
        }
    )
