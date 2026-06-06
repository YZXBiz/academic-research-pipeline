"""Unit tests for the concrete citation resolvers.

Pure parsers run directly; the factories run against a fake `http_get` (URL-routed)
and a fake S2 search, so nothing here touches the network.
"""

from __future__ import annotations

import json

import pytest

from academic_pipeline.models.citation_verification import CitedWork, QueryForm, ResolverStatus
from academic_pipeline.tools.bibliography.resolvers import (
    _arxiv_candidates,
    _crossref_candidates,
    _datacite_candidates,
    _openalex_candidates,
    _openlibrary_candidates,
    _s2_candidates,
    make_arxiv_resolver,
    make_crossref_resolver,
    make_datacite_resolver,
    make_isbn_resolver,
    make_openalex_resolver,
    make_s2_resolver,
)


_CROSSREF_WORK = json.dumps(
    {
        "message": {
            "title": ["Attention Is All You Need"],
            "author": [{"family": "Vaswani"}, {"family": "Shazeer"}],
            "published": {"date-parts": [[2017]]},
            "DOI": "10.1/attn",
        }
    }
)
_CROSSREF_SEARCH = json.dumps({"message": {"items": [json.loads(_CROSSREF_WORK)["message"]]}})
_RA_CROSSREF = json.dumps([{"DOI": "10.1/attn", "RA": "Crossref"}])
_RA_DATACITE = json.dumps([{"DOI": "10.5281/zenodo.1", "RA": "DataCite"}])
_ARXIV_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T00:00:00Z</published>
    <author><name>Ashish Vaswani</name></author>
  </entry>
</feed>"""
_ARXIV_EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
_S2_MATCH = json.dumps(
    {
        "query": "x",
        "matches": [
            {
                "doi": "10.1/attn",
                "title": "Attention Is All You Need",
                "year": 2017,
                "authors": ["Vaswani"],
                "similarity": 1.0,
            }
        ],
    }
)
_S2_DEGRADED = json.dumps({"degraded": True, "error": "boom"})


def _work(**kw: object) -> CitedWork:
    base: dict[str, object] = {
        "source_id": "s1",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani"],
        "year": 2017,
    }
    base.update(kw)
    return CitedWork(**base)  # type: ignore[arg-type]


def _fake_http(routes: dict[str, tuple[int, str]]):
    async def _g(url: str, _headers: object = None) -> tuple[int, str]:
        for frag, resp in routes.items():
            if frag in url:
                return resp
        return (404, "")

    return _g


def _fake_search(result: str):
    async def _s(_title: str) -> str:
        return result

    return _s


class TestPureParsers:
    def test_crossref_message_to_candidate(self) -> None:
        cands = _crossref_candidates([json.loads(_CROSSREF_WORK)["message"]])
        assert len(cands) == 1
        assert cands[0].identifier == "10.1/attn"
        assert cands[0].title == "Attention Is All You Need"
        assert cands[0].authors == ["Vaswani", "Shazeer"]
        assert cands[0].year == 2017

    def test_crossref_search_items(self) -> None:
        cands = _crossref_candidates(json.loads(_CROSSREF_SEARCH)["message"]["items"])
        assert len(cands) == 1

    def test_arxiv_atom_parse(self) -> None:
        cands = _arxiv_candidates(_ARXIV_ATOM)
        assert len(cands) == 1
        assert cands[0].title == "Attention Is All You Need"
        assert cands[0].year == 2017
        assert "Ashish Vaswani" in cands[0].authors

    def test_arxiv_empty_feed(self) -> None:
        assert _arxiv_candidates(_ARXIV_EMPTY) == []

    def test_s2_candidates(self) -> None:
        cands = _s2_candidates(_S2_MATCH)
        assert cands is not None
        assert cands[0].identifier == "10.1/attn"

    def test_s2_degraded_is_none(self) -> None:
        assert _s2_candidates(_S2_DEGRADED) is None


pytestmark = pytest.mark.anyio


class TestCrossrefResolver:
    async def test_id_keyed_match(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_CROSSREF), "api.crossref.org": (200, _CROSSREF_WORK)})
        out = await make_crossref_resolver(http_get=http)(_work(doi="10.1/attn"))
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.ID
        assert out.matched_doi == "10.1/attn"

    async def test_id_keyed_404_is_unmatched(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_CROSSREF), "api.crossref.org": (404, "")})
        out = await make_crossref_resolver(http_get=http)(_work(doi="10.1/bogus"))
        assert out.status is ResolverStatus.UNMATCHED
        assert out.queried_by is QueryForm.ID

    async def test_non_crossref_doi_is_skipped(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_DATACITE)})
        out = await make_crossref_resolver(http_get=http)(_work(doi="10.5281/zenodo.1"))
        assert out.status is ResolverStatus.SKIPPED

    async def test_title_fallback_match_when_no_doi(self) -> None:
        http = _fake_http({"api.crossref.org": (200, _CROSSREF_SEARCH)})
        out = await make_crossref_resolver(http_get=http)(_work(doi=None))
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.TITLE

    async def test_server_error_is_unreachable(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_CROSSREF), "api.crossref.org": (503, "")})
        out = await make_crossref_resolver(http_get=http)(_work(doi="10.1/attn"))
        assert out.status is ResolverStatus.UNREACHABLE


class TestArxivResolver:
    async def test_skipped_without_arxiv_id(self) -> None:
        out = await make_arxiv_resolver(http_get=_fake_http({}))(_work())
        assert out.status is ResolverStatus.SKIPPED

    async def test_id_keyed_match(self) -> None:
        http = _fake_http({"export.arxiv.org": (200, _ARXIV_ATOM)})
        out = await make_arxiv_resolver(http_get=http)(_work(arxiv_id="1706.03762"))
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.ID

    async def test_empty_feed_is_unmatched(self) -> None:
        http = _fake_http({"export.arxiv.org": (200, _ARXIV_EMPTY)})
        out = await make_arxiv_resolver(http_get=http)(_work(arxiv_id="0000.00000"))
        assert out.status is ResolverStatus.UNMATCHED
        assert out.queried_by is QueryForm.ID

    async def test_error_is_unreachable(self) -> None:
        http = _fake_http({"export.arxiv.org": (503, "")})
        out = await make_arxiv_resolver(http_get=http)(_work(arxiv_id="1706.03762"))
        assert out.status is ResolverStatus.UNREACHABLE


class TestS2Resolver:
    async def test_title_match(self) -> None:
        out = await make_s2_resolver(search=_fake_search(_S2_MATCH))(_work())
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.TITLE

    async def test_degraded_is_unreachable(self) -> None:
        out = await make_s2_resolver(search=_fake_search(_S2_DEGRADED))(_work())
        assert out.status is ResolverStatus.UNREACHABLE


_OPENALEX = json.dumps(
    {
        "results": [
            {
                "title": "Attention Is All You Need",
                "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
                "publication_year": 2017,
                "doi": "https://doi.org/10.1/attn",
            }
        ]
    }
)
_OPENALEX_EMPTY = json.dumps({"results": []})
_DATACITE = json.dumps(
    {
        "data": {
            "attributes": {
                "titles": [{"title": "My Dataset"}],
                "creators": [{"familyName": "Vaswani"}],
                "publicationYear": 2017,
                "doi": "10.5281/zenodo.1",
            }
        }
    }
)
_OPENLIB = json.dumps({"title": "Some Book", "publish_date": "2017", "authors": [{"key": "/authors/OL1A"}]})


class TestNewParsers:
    def test_openalex_strips_doi_prefix(self) -> None:
        cands = _openalex_candidates(_OPENALEX)
        assert cands[0].identifier == "10.1/attn"
        assert cands[0].year == 2017

    def test_datacite_parse(self) -> None:
        cands = _datacite_candidates(_DATACITE)
        assert cands[0].title == "My Dataset"
        assert cands[0].authors == ["Vaswani"]

    def test_openlibrary_year_from_publish_date(self) -> None:
        cands = _openlibrary_candidates(_OPENLIB, "9780000000000")
        assert cands[0].title == "Some Book"
        assert cands[0].year == 2017


class TestOpenAlexResolver:
    async def test_id_match(self) -> None:
        http = _fake_http({"api.openalex.org": (200, _OPENALEX)})
        out = await make_openalex_resolver(http_get=http)(_work(doi="10.1/attn"))
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.ID

    async def test_id_empty_is_unmatched(self) -> None:
        http = _fake_http({"api.openalex.org": (200, _OPENALEX_EMPTY)})
        out = await make_openalex_resolver(http_get=http)(_work(doi="10.1/bogus"))
        assert out.status is ResolverStatus.UNMATCHED


class TestDataCiteResolver:
    async def test_skip_non_datacite_doi(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_CROSSREF)})
        out = await make_datacite_resolver(http_get=http)(_work(doi="10.1/attn"))
        assert out.status is ResolverStatus.SKIPPED

    async def test_match_datacite_doi(self) -> None:
        http = _fake_http({"doi.org/ra": (200, _RA_DATACITE), "api.datacite.org": (200, _DATACITE)})
        out = await make_datacite_resolver(http_get=http)(
            _work(title="My Dataset", authors=["Vaswani"], year=2017, doi="10.5281/zenodo.1")
        )
        assert out.status is ResolverStatus.MATCHED
        assert out.queried_by is QueryForm.ID


class TestIsbnResolver:
    async def test_skip_without_isbn(self) -> None:
        out = await make_isbn_resolver(http_get=_fake_http({}))(_work())
        assert out.status is ResolverStatus.SKIPPED

    async def test_match(self) -> None:
        http = _fake_http({"openlibrary.org": (200, _OPENLIB)})
        out = await make_isbn_resolver(http_get=http)(
            _work(title="Some Book", authors=["Knuth"], year=2017, isbn="9780000000000")
        )
        assert out.status is ResolverStatus.MATCHED
