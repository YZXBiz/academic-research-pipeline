"""CrossRef / arXiv / Semantic Scholar resolvers for the citation-existence gate."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import httpx

from academic_pipeline.config import DEFAULT_CONFIG
from academic_pipeline.models.citation_verification import QueryForm, ResolverOutcome, ResolverStatus
from academic_pipeline.tools.bibliography.citation_verifier import Candidate, MatchResult, metadata_match
from academic_pipeline.tools.bibliography.semantic_scholar import search_s2_by_title


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from academic_pipeline.models.citation_verification import CitedWork

    HttpGet = Callable[[str, Mapping[str, str] | None], Awaitable[tuple[int, str]]]
    S2Search = Callable[[str], Awaitable[str]]
    Resolver = Callable[[CitedWork], Awaitable[ResolverOutcome]]


logger = logging.getLogger(__name__)

_CROSSREF_WORKS = "https://api.crossref.org/works"
_DOI_RA = "https://doi.org/ra"
_ARXIV_API = "http://export.arxiv.org/api/query"
_OPENALEX_WORKS = "https://api.openalex.org/works"
_DATACITE_DOIS = "https://api.datacite.org/dois"
_OPENLIBRARY_ISBN = "https://openlibrary.org/isbn"
_DEFAULT_MAILTO = "academic-pipeline@users.noreply.github.com"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}


async def _httpx_get(url: str, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
    async with httpx.AsyncClient(
        verify=DEFAULT_CONFIG.ssl_verify,
        timeout=DEFAULT_CONFIG.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "AcademicPipeline/1.0"},
    ) as client:
        resp = await client.get(url, headers=dict(headers) if headers else None)
        return resp.status_code, resp.text


def _crossref_candidates(items: list[dict]) -> list[Candidate]:
    out: list[Candidate] = []
    for it in items:
        title_field = it.get("title") or [""]
        title = title_field[0] if isinstance(title_field, list) and title_field else str(title_field)
        authors = [a.get("family", "") for a in (it.get("author") or []) if a.get("family")]
        year: int | None = None
        date_parts = ((it.get("published") or it.get("issued") or {}).get("date-parts")) or []
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
        out.append(Candidate(identifier=it.get("DOI"), title=title, authors=authors, year=year))
    return out


def _arxiv_candidates(atom_xml: str) -> list[Candidate]:
    root = ET.fromstring(atom_xml)
    out: list[Candidate] = []
    for entry in root.findall("a:entry", _ATOM):
        title = (entry.findtext("a:title", default="", namespaces=_ATOM) or "").strip()
        authors = [(n.text or "").strip() for n in entry.findall("a:author/a:name", _ATOM)]
        published = entry.findtext("a:published", default="", namespaces=_ATOM) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        arxiv_id = (entry.findtext("a:id", default="", namespaces=_ATOM) or "").strip() or None
        out.append(Candidate(identifier=arxiv_id, title=title, authors=authors, year=year))
    return out


def _s2_candidates(search_json: str) -> list[Candidate] | None:
    """Returns None when the S2 search was degraded (treated as UNREACHABLE)."""
    data = json.loads(search_json)
    if data.get("degraded"):
        return None
    return [
        Candidate(
            identifier=(m.get("doi") or None),
            title=m.get("title", ""),
            authors=list(m.get("authors") or []),
            year=m.get("year"),
        )
        for m in data.get("matches", [])
    ]


def _openalex_candidates(payload: str) -> list[Candidate]:
    out: list[Candidate] = []
    for r in json.loads(payload).get("results") or []:
        authors = [a.get("author", {}).get("display_name", "") for a in (r.get("authorships") or [])]
        doi = r.get("doi")
        if doi:
            doi = doi.removeprefix("https://doi.org/")
        out.append(
            Candidate(
                identifier=doi,
                title=r.get("title") or "",
                authors=[a for a in authors if a],
                year=r.get("publication_year"),
            )
        )
    return out


def _datacite_candidates(payload: str) -> list[Candidate]:
    attrs = (json.loads(payload).get("data") or {}).get("attributes") or {}
    titles = attrs.get("titles") or []
    title = titles[0].get("title", "") if titles else ""
    authors = [c.get("familyName") or c.get("name", "") for c in (attrs.get("creators") or [])]
    return [
        Candidate(
            identifier=attrs.get("doi"),
            title=title,
            authors=[a for a in authors if a],
            year=attrs.get("publicationYear"),
        )
    ]


def _openlibrary_candidates(payload: str, isbn: str) -> list[Candidate]:
    data = json.loads(payload)
    year_match = re.search(r"\d{4}", data.get("publish_date", "") or "")
    return [
        Candidate(
            identifier=isbn,
            title=data.get("title", ""),
            authors=[],
            year=int(year_match.group()) if year_match else None,
        )
    ]


def _outcome(match: MatchResult, queried_by: QueryForm, *, summary: str | None = None) -> ResolverOutcome:
    if match.matched:
        return ResolverOutcome(
            status=ResolverStatus.MATCHED,
            queried_by=queried_by,
            matched_doi=match.matched_id,
            matched_year=match.matched_year,
            response_summary=summary,
        )
    return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=queried_by, response_summary=summary)


async def registration_agency(doi: str, http_get: HttpGet) -> str | None:
    """DOI registration agency, or None if unknown/nonexistent/error (CrossRef decides)."""
    try:
        status, body = await http_get(f"{_DOI_RA}/{urllib.parse.quote(doi)}", None)
    except Exception as exc:
        logger.debug("registration_agency lookup failed for %s: %r", doi, exc)
        return None
    if status != 200:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list) and payload:
        return payload[0].get("RA")
    return None


def make_crossref_resolver(*, http_get: HttpGet = _httpx_get, mailto: str = _DEFAULT_MAILTO) -> Resolver:
    """CrossRef resolver: ID-keyed when a DOI is present (skips non-CrossRef DOIs), else title fallback."""
    headers = {"User-Agent": f"AcademicPipeline/1.0 (mailto:{mailto})"}

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        if work.doi:
            agency = await registration_agency(work.doi, http_get)
            if agency is not None and agency.lower() != "crossref":
                return ResolverOutcome(
                    status=ResolverStatus.SKIPPED,
                    response_summary=f"DOI registered with {agency}, not CrossRef",
                )
            status, body = await http_get(f"{_CROSSREF_WORKS}/{urllib.parse.quote(work.doi)}", headers)
            if status == 404:
                return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=QueryForm.ID)
            if status != 200:
                return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"crossref status {status}")
            message = json.loads(body).get("message", {})
            return _outcome(metadata_match(work, _crossref_candidates([message])), QueryForm.ID)

        query = urllib.parse.urlencode({"query.bibliographic": work.title, "rows": "5"})
        status, body = await http_get(f"{_CROSSREF_WORKS}?{query}", headers)
        if status != 200:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"crossref status {status}")
        items = json.loads(body).get("message", {}).get("items", [])
        return _outcome(metadata_match(work, _crossref_candidates(items)), QueryForm.TITLE)

    return _resolve


def make_arxiv_resolver(*, http_get: HttpGet = _httpx_get) -> Resolver:
    """ArXiv resolver: ID-keyed only; skips a citation with no arXiv ID."""

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        if not work.arxiv_id:
            return ResolverOutcome(status=ResolverStatus.SKIPPED, response_summary="no arXiv ID")
        query = urllib.parse.urlencode({"id_list": work.arxiv_id})
        status, body = await http_get(f"{_ARXIV_API}?{query}", None)
        if status != 200:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"arxiv status {status}")
        candidates = _arxiv_candidates(body)
        if not candidates:
            return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=QueryForm.ID)
        return _outcome(metadata_match(work, candidates), QueryForm.ID)

    return _resolve


def make_s2_resolver(*, search: S2Search = search_s2_by_title) -> Resolver:
    """Semantic Scholar resolver: title-keyed."""

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        candidates = _s2_candidates(await search(work.title))
        if candidates is None:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary="s2 degraded")
        return _outcome(metadata_match(work, candidates), QueryForm.TITLE)

    return _resolve


def make_openalex_resolver(*, http_get: HttpGet = _httpx_get, mailto: str = _DEFAULT_MAILTO) -> Resolver:
    """OpenAlex resolver: ID-keyed by DOI, else title fallback."""

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        if work.doi:
            url = f"{_OPENALEX_WORKS}?filter=doi:{urllib.parse.quote(work.doi)}&mailto={mailto}"
            queried_by = QueryForm.ID
        else:
            url = f"{_OPENALEX_WORKS}?search={urllib.parse.quote(work.title)}&per_page=5&mailto={mailto}"
            queried_by = QueryForm.TITLE
        status, body = await http_get(url, None)
        if status != 200:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"openalex status {status}")
        candidates = _openalex_candidates(body)
        if queried_by is QueryForm.ID and not candidates:
            return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=QueryForm.ID)
        return _outcome(metadata_match(work, candidates), queried_by)

    return _resolve


def make_datacite_resolver(*, http_get: HttpGet = _httpx_get) -> Resolver:
    """DataCite resolver: ID-keyed; runs only for DataCite-registered DOIs."""

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        if not work.doi:
            return ResolverOutcome(status=ResolverStatus.SKIPPED, response_summary="no DOI")
        agency = await registration_agency(work.doi, http_get)
        if agency is None or agency.lower() != "datacite":
            return ResolverOutcome(status=ResolverStatus.SKIPPED, response_summary="not a DataCite DOI")
        status, body = await http_get(f"{_DATACITE_DOIS}/{urllib.parse.quote(work.doi)}", None)
        if status == 404:
            return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=QueryForm.ID)
        if status != 200:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"datacite status {status}")
        return _outcome(metadata_match(work, _datacite_candidates(body)), QueryForm.ID)

    return _resolve


def make_isbn_resolver(*, http_get: HttpGet = _httpx_get) -> Resolver:
    """ISBN resolver (OpenLibrary): ID-keyed; skips a citation with no ISBN."""

    async def _resolve(work: CitedWork) -> ResolverOutcome:
        if not work.isbn:
            return ResolverOutcome(status=ResolverStatus.SKIPPED, response_summary="no ISBN")
        status, body = await http_get(f"{_OPENLIBRARY_ISBN}/{urllib.parse.quote(work.isbn)}.json", None)
        if status == 404:
            return ResolverOutcome(status=ResolverStatus.UNMATCHED, queried_by=QueryForm.ID)
        if status != 200:
            return ResolverOutcome(status=ResolverStatus.UNREACHABLE, response_summary=f"openlibrary status {status}")
        return _outcome(metadata_match(work, _openlibrary_candidates(body, work.isbn)), QueryForm.ID)

    return _resolve


def _rate_limited(http_get: HttpGet, *, concurrency: int, min_interval: float = 0.0) -> HttpGet:
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    last = 0.0

    async def _wrapped(url: str, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        nonlocal last
        async with sem:
            if min_interval:
                async with lock:
                    loop = asyncio.get_running_loop()
                    wait = min_interval - (loop.time() - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last = loop.time()
            return await http_get(url, headers)

    return _wrapped


def default_resolvers(
    *,
    http_get: HttpGet = _httpx_get,
    mailto: str = _DEFAULT_MAILTO,
    s2_search: S2Search = search_s2_by_title,
) -> dict[str, Resolver]:
    """Full resolver set: CrossRef + OpenAlex + DataCite + ISBN + arXiv + Semantic Scholar, rate-limited."""
    return {
        "crossref": make_crossref_resolver(http_get=_rate_limited(http_get, concurrency=3), mailto=mailto),
        "openalex": make_openalex_resolver(http_get=_rate_limited(http_get, concurrency=4), mailto=mailto),
        "datacite": make_datacite_resolver(http_get=_rate_limited(http_get, concurrency=4)),
        "isbn": make_isbn_resolver(http_get=_rate_limited(http_get, concurrency=4)),
        "arxiv": make_arxiv_resolver(http_get=_rate_limited(http_get, concurrency=1, min_interval=3.0)),
        "s2": make_s2_resolver(search=s2_search),
    }
