"""Async DOI verification tools for PydanticAI agents.

Verify DOIs, check retraction status, and resolve bibliographic metadata
via doi.org and CrossRef APIs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
from pydantic_ai import ModelRetry

from academic_pipeline.config import DEFAULT_CONFIG


logger = logging.getLogger(__name__)

_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[^\s]+$")
_CROSSREF_HEADERS = {
    "User-Agent": "AcademicPipeline/1.0 (mailto:academic-pipeline@users.noreply.github.com)",
}

ASYNC_NETWORK_ERRORS = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.ConnectError,
    OSError,
    ValueError,
)


def _clean_doi(doi: str) -> str:
    """Strip URL prefixes and whitespace from a DOI string."""
    return doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/").strip()


def _validate_doi_format(doi: str) -> str | None:
    """Return an error message if DOI format is invalid, else None."""
    if not doi:
        return "Empty DOI"
    if not _DOI_PATTERN.match(doi):
        return f"Invalid DOI format: {doi}"
    return None


async def _async_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Perform an async HTTP request using httpx.AsyncClient.

    Args:
        url: The URL to fetch.
        method: HTTP method to use ("GET" or "HEAD").
        headers: Optional extra HTTP headers.

    Returns:
        The httpx.Response from the request.
    """
    async with httpx.AsyncClient(
        verify=DEFAULT_CONFIG.ssl_verify,
        timeout=DEFAULT_CONFIG.http_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "AcademicPipeline/1.0"},
    ) as client:
        if method.upper() == "HEAD":
            return await client.head(url, headers=headers)
        return await client.get(url, headers=headers)


async def verify_doi(doi: str) -> str:
    """Verify that a DOI exists by resolving it through doi.org.

    Args:
        doi: The DOI string to verify (may include URL prefix).

    Returns:
        JSON string with doi, exists (bool), resolved_url, and status.
    """
    clean_doi = _clean_doi(doi)
    format_error = _validate_doi_format(clean_doi)
    if format_error:
        raise ModelRetry(
            f"Invalid DOI format '{clean_doi}': {format_error}. " "Provide a valid DOI like '10.1234/example'."
        )

    url = f"https://doi.org/{clean_doi}"
    try:
        resp = await _async_fetch(url, method="HEAD")
        if resp.status_code in (200, 301, 302, 303, 307, 308):
            return json.dumps(
                {
                    "doi": clean_doi,
                    "exists": True,
                    "resolved_url": str(resp.headers.get("location", url)),
                    "status": resp.status_code,
                }
            )
        return json.dumps(
            {
                "doi": clean_doi,
                "exists": False,
                "status": resp.status_code,
                "error": "DOI not found",
            }
        )
    except ASYNC_NETWORK_ERRORS as e:
        logger.warning("DOI verification failed for %s: %s", clean_doi, e)
        return json.dumps({"doi": clean_doi, "exists": False, "error": str(e)})


async def check_retraction(doi: str) -> str:
    """Check if a paper identified by DOI has been retracted via CrossRef.

    Args:
        doi: The DOI string to check for retraction (may include URL prefix).

    Returns:
        JSON string with doi, retracted status, and related metadata.
    """
    clean_doi = _clean_doi(doi)
    format_error = _validate_doi_format(clean_doi)
    if format_error:
        raise ModelRetry(
            f"Invalid DOI format '{clean_doi}': {format_error}. " "Provide a valid DOI like '10.1234/example'."
        )

    url = f"https://api.crossref.org/works/{clean_doi}"
    try:
        resp = await _async_fetch(url, headers=_CROSSREF_HEADERS)
        if resp.status_code == 404:
            return json.dumps(
                {
                    "doi": clean_doi,
                    "retracted": "unknown",
                    "reason": "DOI not found in CrossRef",
                }
            )
        resp.raise_for_status()
        data = resp.json().get("message", {})
    except ASYNC_NETWORK_ERRORS as e:
        logger.warning("Retraction check failed for %s: %s", clean_doi, e)
        return json.dumps({"doi": clean_doi, "retracted": "unknown", "error": str(e)})

    update_to = data.get("update-to", [])
    for update in update_to:
        if update.get("type") == "retraction":
            return json.dumps(
                {
                    "doi": clean_doi,
                    "retracted": True,
                    "retraction_doi": update.get("DOI", ""),
                    "retraction_date": update.get("updated", {}).get("date-parts", []),
                }
            )

    return json.dumps(
        {
            "doi": clean_doi,
            "retracted": False,
            "title": (data.get("title", [""])[0] if data.get("title") else ""),
            "type": data.get("type", ""),
        }
    )


async def resolve_doi_metadata(doi: str) -> str:
    """Resolve a DOI to its full bibliographic metadata via CrossRef.

    Args:
        doi: The DOI string to resolve (may include URL prefix).

    Returns:
        JSON string with found (bool) and bibliographic fields including: title, authors, year, journal, volume, issue,
            pages, type, publisher, issn, and url.
    """
    clean_doi = _clean_doi(doi)
    format_error = _validate_doi_format(clean_doi)
    if format_error:
        raise ModelRetry(
            f"Invalid DOI format '{clean_doi}': {format_error}. " "Provide a valid DOI like '10.1234/example'."
        )

    url = f"https://api.crossref.org/works/{clean_doi}"
    try:
        resp = await _async_fetch(url, headers=_CROSSREF_HEADERS)
        if resp.status_code == 404:
            return json.dumps({"doi": clean_doi, "found": False, "error": "Not in CrossRef"})
        resp.raise_for_status()
        msg = resp.json().get("message", {})
    except ASYNC_NETWORK_ERRORS as e:
        logger.warning("DOI metadata resolution failed for %s: %s", clean_doi, e)
        return json.dumps({"doi": clean_doi, "found": False, "error": str(e)})

    authors = [f"{a.get('family', '')}, {a.get('given', '')}" for a in (msg.get("author") or [])]
    date_parts = (msg.get("published-print") or msg.get("published-online") or {}).get("date-parts", [[]])
    year = date_parts[0][0] if date_parts and date_parts[0] else None

    return json.dumps(
        {
            "doi": clean_doi,
            "found": True,
            "title": (msg.get("title") or [""])[0],
            "authors": authors,
            "year": year,
            "journal": (msg.get("container-title") or [""])[0],
            "volume": msg.get("volume", ""),
            "issue": msg.get("issue", ""),
            "pages": msg.get("page", ""),
            "type": msg.get("type", ""),
            "publisher": msg.get("publisher", ""),
            "issn": msg.get("ISSN", []),
            "url": msg.get("URL", ""),
        }
    )


# §6.7.T2 build-gate parsers (kept minimal — full bibtex parser is overkill).
_BIB_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,([^@]+)", re.MULTILINE)
_BIB_DOI_FIELD_RE = re.compile(r"\bdoi\s*=\s*\{?([^,}\n]+)", re.IGNORECASE)
_DOI_PLACEHOLDER_VALUES = frozenset({"none", "null", "n/a", ""})


def _parse_bibtex_entries(bibtex: str) -> list[dict[str, str | None]]:
    """Yield ``[{key, doi}]`` for each ``@type{...}`` entry in *bibtex*.

    ``doi`` is ``None`` when the field is absent OR holds a placeholder
    (``None``/``null``/``n/a``/empty). Used by ``verify_dois_in_bibtex`` to
    skip entries that don't claim a DOI from the verification workload.
    """
    entries: list[dict[str, str | None]] = []
    for match in _BIB_ENTRY_RE.finditer(bibtex):
        key = match.group(1).strip()
        body = match.group(2)
        doi: str | None = None
        doi_match = _BIB_DOI_FIELD_RE.search(body)
        if doi_match:
            candidate = doi_match.group(1).strip().rstrip("}").strip()
            if candidate.lower() not in _DOI_PLACEHOLDER_VALUES:
                doi = candidate
        entries.append({"key": key, "doi": doi})
    return entries


async def verify_dois_in_bibtex(bibtex: str) -> list[dict[str, object]]:
    """Verify every DOI-bearing entry in *bibtex* against doi.org in parallel.

    Used by the §6.7.T2 build gate inside ``compile_pdf_pandoc``. Entries
    without a DOI field (or with a placeholder value) are skipped — the
    gate's policy is to verify what's claimed, not to require DOIs on
    every entry.

    Args:
        bibtex: full bibtex source string.

    Returns:
        One ``{key, doi, verified, crossref_status}`` dict per DOI-bearing
        entry. ``verified`` is ``True`` iff doi.org returned a 2xx/3xx for the
        DOI; ``crossref_status`` is the raw integer status (``0`` on
        network error). Order preserves bibtex order. Empty list when the
        input has no DOI-bearing entries.
    """
    entries = [e for e in _parse_bibtex_entries(bibtex) if e["doi"]]
    if not entries:
        return []

    async def _check(entry: dict[str, str | None]) -> dict[str, object]:
        doi = entry["doi"]
        assert doi is not None  # filtered above
        try:
            payload = json.loads(await verify_doi(doi))
        except (ModelRetry, ValueError, json.JSONDecodeError) as e:
            logger.warning("verify_doi raised for %s: %s", doi, e)
            return {
                "key": entry["key"],
                "doi": doi,
                "verified": False,
                "crossref_status": 0,
            }
        return {
            "key": entry["key"],
            "doi": doi,
            "verified": bool(payload.get("exists")),
            "crossref_status": int(payload.get("status", 0) or 0),
        }

    return list(await asyncio.gather(*(_check(e) for e in entries)))
