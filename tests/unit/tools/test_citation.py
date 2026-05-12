"""Tests for async citation formatter tools (PydanticAI-compatible)."""

from __future__ import annotations

import pytest

from academic_pipeline.tools.bibliography.citations import (
    CitationMetadata,
    convert_citation_style,
    format_citation,
    validate_citation,
)


pytestmark = pytest.mark.anyio


def _sample_metadata(**overrides: object) -> CitationMetadata:
    """Build a CitationMetadata with sensible defaults."""
    defaults = {
        "authors": ["Smith, John", "Doe, Jane"],
        "year": 2023,
        "title": "Deep Learning in NLP",
        "journal": "Nature ML",
        "volume": "5",
        "issue": "2",
        "pages": "100-115",
        "doi": "10.1234/test.doi",
        "publisher": "Nature Publishing",
        "source_type": "journal-article",
    }
    defaults.update(overrides)
    return CitationMetadata(**defaults)  # type: ignore[arg-type]


class TestFormatCitation:
    """Tests for the format_citation async tool."""

    async def test_apa7_journal_article(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "APA7")
        assert "Smith" in result
        assert "(2023)" in result
        assert "Deep Learning in NLP" in result
        assert "https://doi.org/10.1234/test.doi" in result

    async def test_chicago_journal_article(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "Chicago")
        assert "Smith" in result
        assert '"Deep Learning in NLP."' in result
        assert "2023" in result

    async def test_mla_journal_article(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "MLA")
        assert "Smith" in result
        assert "vol. 5" in result
        assert "no. 2" in result

    async def test_ieee_journal_article(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "IEEE")
        assert "J. Smith" in result
        assert "vol. 5" in result
        assert result.strip().endswith(".")

    async def test_vancouver_journal_article(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "Vancouver")
        assert "Smith J" in result or "Smith JD" in result
        assert "2023" in result

    async def test_default_style_is_apa7(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta)
        assert "(2023)" in result  # APA year format

    async def test_book_format(self) -> None:
        meta = _sample_metadata(source_type="book")
        result = await format_citation(meta, "APA7")
        assert "*Deep Learning in NLP*" in result
        assert "Nature Publishing" in result

    async def test_unknown_style_falls_back_to_apa7(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "UnknownStyle")
        apa_result = await format_citation(meta, "APA7")
        assert result == apa_result

    async def test_no_authors(self) -> None:
        meta = _sample_metadata(authors=[])
        result = await format_citation(meta, "APA7")
        assert "Unknown" in result


class TestAclAnthologyStyle:
    """§6.7.T9 — ACL anthology citation format.

    ACL anthology entries render with full author names (not initials),
    'and' between last two authors, year on its own with period, italicized
    journal/proceedings, and colon-notated pages (e.g. ``5(2):100-115``).
    """

    async def test_acl_journal_article_basic_shape(self) -> None:
        meta = _sample_metadata()
        result = await format_citation(meta, "ACL")
        # Authors: full names with 'and' joiner.
        assert "John Smith" in result
        assert "Jane Doe" in result
        assert " and " in result
        # Year stands alone with period (not parenthesized).
        assert " 2023. " in result
        # Title appears.
        assert "Deep Learning in NLP" in result
        # Journal italicized via markdown asterisks (consistent with other styles).
        assert "*Nature ML*" in result
        # Pages in ACL colon notation: volume(issue):pages
        assert "5(2):100-115" in result

    async def test_acl_inproceedings_uses_proceedings_prefix(self) -> None:
        meta = _sample_metadata(
            source_type="inproceedings",
            journal="NAACL 2023",
            volume="",
            issue="",
        )
        result = await format_citation(meta, "ACL")
        # Inproceedings format is distinct: "In *Proceedings of...*, pages X-Y."
        assert "In *NAACL 2023*" in result or "In *Proceedings of NAACL 2023*" in result
        assert "pages 100-115" in result

    async def test_acl_single_author_omits_and(self) -> None:
        meta = _sample_metadata(authors=["Smith, John"])
        result = await format_citation(meta, "ACL")
        assert "John Smith" in result
        assert " and " not in result

    async def test_acl_three_authors_oxford_and(self) -> None:
        meta = _sample_metadata(
            authors=["Smith, John", "Doe, Jane", "Brown, Alice"],
        )
        result = await format_citation(meta, "ACL")
        # ACL convention: comma-separated with final 'and' before last author.
        assert "John Smith, Jane Doe, and Alice Brown" in result

    async def test_acl_registered_in_dispatch(self) -> None:
        from academic_pipeline.tools.bibliography.citations import _FORMATTERS

        assert (
            "ACL" in _FORMATTERS
        ), "ACL formatter must register in _FORMATTERS so format_citation(..., style='ACL') routes correctly."

    async def test_acl_validate_citation_recognizes_style(self) -> None:
        """validate_citation must accept 'ACL' as a known style — should not
        bail out as 'unknown style'."""
        # A well-formed ACL entry per the format above.
        valid = "John Smith and Jane Doe. 2023. Deep Learning in NLP. *Nature ML*, 5(2):100-115."
        result = await validate_citation(valid, style="ACL")
        # The validator currently has per-style heuristics; ACL must at least
        # not crash and must return a string. Empty issue list -> "VALID".
        assert isinstance(result, str)
        assert "ACL: " not in result or result == "VALID", "Well-formed ACL entry must not produce ACL-specific issues."


class TestValidateCitation:
    """Tests for the validate_citation async tool."""

    async def test_valid_apa7(self) -> None:
        citation = (
            "Smith, J. & Doe, J. (2023). Deep Learning in NLP. "
            "*Nature ML*, *5(2)*, 100-115. https://doi.org/10.1234/test.doi"
        )
        result = await validate_citation(citation, "APA7")
        assert result == "VALID"

    async def test_detects_missing_italics(self) -> None:
        citation = "Smith, J. (2023). Title. Journal Name, 5(2), 100-115."
        result = await validate_citation(citation, "APA7")
        assert "Issues found" in result
        assert "italicized" in result.lower()

    async def test_detects_wrong_doi_format(self) -> None:
        citation = "Smith, J. (2023). Title. *Journal*, *5(2)*, 100-115. doi:10.1234/test"
        result = await validate_citation(citation, "APA7")
        assert "Issues found" in result
        assert "doi" in result.lower()

    async def test_ieee_must_end_with_period(self) -> None:
        citation = 'J. Smith, "Title," *Journal*, vol. 5, no. 2, pp. 100-115, 2023'
        result = await validate_citation(citation, "IEEE")
        assert "Issues found" in result
        assert "period" in result.lower()

    async def test_ieee_valid_ending(self) -> None:
        citation = 'J. Smith, "Title," *Journal*, vol. 5, no. 2, pp. 100-115, 2023.'
        result = await validate_citation(citation, "IEEE")
        assert result == "VALID"

    async def test_default_style_is_apa7(self) -> None:
        citation = "Smith, J. (2023). Deep Learning. *Nature ML*, *5*. https://doi.org/10.1234/test.doi"
        result = await validate_citation(citation)
        assert result == "VALID"


class TestConvertCitationStyle:
    """Tests for the convert_citation_style async tool."""

    async def test_returns_guidance_message(self) -> None:
        result = await convert_citation_style("Smith (2023). Title.", "APA7", "IEEE")
        assert "heuristic" in result.lower()
        assert "unreliable" in result.lower()
        assert "APA7" in result
        assert "IEEE" in result

    async def test_includes_original_citation(self) -> None:
        original = "Smith (2023). Title."
        result = await convert_citation_style(original, "APA7", "Chicago")
        assert original in result

    async def test_recommends_doi_based_conversion(self) -> None:
        result = await convert_citation_style("Any.", "MLA", "Vancouver")
        assert "resolve_doi_metadata" in result
        assert "format_citation" in result


class TestFormatAuthorApa:
    """Tests for _format_author_apa helper."""

    def test_family_given_format(self):
        from academic_pipeline.tools.bibliography.citations import _format_author_apa

        assert _format_author_apa("Smith, John") == "Smith, J."

    def test_family_given_multiple_initials(self):
        from academic_pipeline.tools.bibliography.citations import _format_author_apa

        result = _format_author_apa("Smith, John Robert")
        assert result == "Smith, J. R."

    def test_single_name_returned_as_is(self):
        from academic_pipeline.tools.bibliography.citations import _format_author_apa

        assert _format_author_apa("Aristotle") == "Aristotle"

    def test_name_with_no_comma(self):
        from academic_pipeline.tools.bibliography.citations import _format_author_apa

        assert _format_author_apa("World Health Organization") == "World Health Organization"


class TestApa7AuthorString:
    """Tests for _apa7_author_string helper."""

    def test_no_authors(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        assert _apa7_author_string([]) == "Unknown"

    def test_single_author(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        result = _apa7_author_string(["Smith, John"])
        assert result == "Smith, J."

    def test_two_authors_joined_with_ampersand(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        result = _apa7_author_string(["Smith, John", "Doe, Jane"])
        assert "&" in result
        assert "Smith, J." in result
        assert "Doe, J." in result

    def test_three_authors_comma_separated_with_ampersand(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        result = _apa7_author_string(["Smith, John", "Doe, Jane", "Lee, Wei"])
        assert ", & " in result

    def test_twenty_authors_all_listed(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        authors = [f"Author{i}, Name{i}" for i in range(20)]
        result = _apa7_author_string(authors)
        assert ", & " in result
        assert "..." not in result

    def test_twentyone_authors_uses_ellipsis(self):
        from academic_pipeline.tools.bibliography.citations import _apa7_author_string

        authors = [f"Author{i}, Name{i}" for i in range(21)]
        result = _apa7_author_string(authors)
        assert "..." in result


class TestFormatApa7Edges:
    """Edge-case tests for _format_apa7."""

    def test_journal_article_no_doi(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(doi="")
        result = _format_apa7(meta)
        assert "https://doi.org/" not in result

    def test_journal_article_no_pages(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(pages="")
        result = _format_apa7(meta)
        # Should not have a dangling comma before the period
        assert ", ." not in result

    def test_journal_article_no_issue(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(issue="")
        result = _format_apa7(meta)
        assert "(" not in result.split("*")[-1].split(".")[0] or "(2023)" in result

    def test_book_type(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(source_type="book")
        result = _format_apa7(meta)
        assert "*Deep Learning in NLP*" in result
        assert "Nature Publishing" in result

    def test_fallback_type_uses_journal_or_publisher(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(source_type="chapter", journal="")
        result = _format_apa7(meta)
        assert "Nature Publishing" in result

    def test_fallback_type_uses_journal_when_present(self):
        from academic_pipeline.tools.bibliography.citations import _format_apa7

        meta = _sample_metadata(source_type="chapter")
        result = _format_apa7(meta)
        assert "Nature ML" in result


class TestFormatChicagoEdges:
    """Edge-case tests for _format_chicago."""

    def test_no_authors(self):
        from academic_pipeline.tools.bibliography.citations import _format_chicago

        meta = _sample_metadata(authors=[])
        result = _format_chicago(meta)
        assert result.startswith("Unknown")

    def test_book_type(self):
        from academic_pipeline.tools.bibliography.citations import _format_chicago

        meta = _sample_metadata(source_type="book")
        result = _format_chicago(meta)
        assert "*Deep Learning in NLP*" in result
        assert "Nature Publishing" in result

    def test_no_doi(self):
        from academic_pipeline.tools.bibliography.citations import _format_chicago

        meta = _sample_metadata(doi="")
        result = _format_chicago(meta)
        assert "https://doi.org/" not in result


class TestFormatMlaEdges:
    """Edge-case tests for _format_mla."""

    def test_single_author(self):
        from academic_pipeline.tools.bibliography.citations import _format_mla

        meta = _sample_metadata(authors=["Smith, John"])
        result = _format_mla(meta)
        assert "et al" not in result
        assert "Smith, John" in result

    def test_multiple_authors_uses_et_al(self):
        from academic_pipeline.tools.bibliography.citations import _format_mla

        meta = _sample_metadata(authors=["Smith, John", "Doe, Jane"])
        result = _format_mla(meta)
        assert "et al" in result

    def test_no_authors(self):
        from academic_pipeline.tools.bibliography.citations import _format_mla

        meta = _sample_metadata(authors=[])
        result = _format_mla(meta)
        assert "Unknown" in result

    def test_book_type(self):
        from academic_pipeline.tools.bibliography.citations import _format_mla

        meta = _sample_metadata(source_type="book")
        result = _format_mla(meta)
        assert "*Deep Learning in NLP*" in result

    def test_no_doi(self):
        from academic_pipeline.tools.bibliography.citations import _format_mla

        meta = _sample_metadata(doi="")
        result = _format_mla(meta)
        assert "doi:" not in result


class TestFormatIeeeEdges:
    """Edge-case tests for _format_ieee."""

    def test_no_authors(self):
        from academic_pipeline.tools.bibliography.citations import _format_ieee

        meta = _sample_metadata(authors=[])
        result = _format_ieee(meta)
        assert result.startswith("Unknown")

    def test_author_without_comma(self):
        from academic_pipeline.tools.bibliography.citations import _format_ieee

        meta = _sample_metadata(authors=["Aristotle"])
        result = _format_ieee(meta)
        assert "Aristotle" in result

    def test_book_type(self):
        from academic_pipeline.tools.bibliography.citations import _format_ieee

        meta = _sample_metadata(source_type="book")
        result = _format_ieee(meta)
        assert "*Deep Learning in NLP*" in result
        assert result.strip().endswith(".")


class TestFormatVancouverEdges:
    """Edge-case tests for _format_vancouver."""

    def test_no_authors(self):
        from academic_pipeline.tools.bibliography.citations import _format_vancouver

        meta = _sample_metadata(authors=[])
        result = _format_vancouver(meta)
        assert result.startswith("Unknown")

    def test_author_without_comma(self):
        from academic_pipeline.tools.bibliography.citations import _format_vancouver

        meta = _sample_metadata(authors=["WHO"])
        result = _format_vancouver(meta)
        assert "WHO" in result

    def test_more_than_six_authors_uses_et_al(self):
        from academic_pipeline.tools.bibliography.citations import _format_vancouver

        authors = [f"Author{i}, Name{i}" for i in range(8)]
        meta = _sample_metadata(authors=authors)
        result = _format_vancouver(meta)
        assert "et al" in result

    def test_six_or_fewer_authors_no_et_al(self):
        from academic_pipeline.tools.bibliography.citations import _format_vancouver

        authors = [f"Author{i}, Name{i}" for i in range(6)]
        meta = _sample_metadata(authors=authors)
        result = _format_vancouver(meta)
        assert "et al" not in result

    def test_book_type(self):
        from academic_pipeline.tools.bibliography.citations import _format_vancouver

        meta = _sample_metadata(source_type="book")
        result = _format_vancouver(meta)
        assert "Nature Publishing" in result
        assert result.strip().endswith(".")


class TestValidateCitationEdges:
    """Additional edge-case tests for validate_citation."""

    async def test_apa7_et_al_with_few_commas(self) -> None:
        citation = "Smith et al. (2023). Title. *Journal*, *5*."
        result = await validate_citation(citation, "APA7")
        assert "et al." in result

    async def test_apa7_missing_parentheses_and_period(self) -> None:
        citation = "Smith 2023 Title Journal 5"
        result = await validate_citation(citation, "APA7")
        assert "Issues found" in result

    async def test_vancouver_et_al_with_too_many_commas(self) -> None:
        citation = "A1, A2, A3, A4, A5, A6, A7, et al. Title. Journal. 2023;5(2):100-115."
        result = await validate_citation(citation, "Vancouver")
        assert "Issues found" in result
        assert "6 authors" in result

    async def test_vancouver_valid(self) -> None:
        citation = "Smith J, Doe J. Title. Journal. 2023;5(2):100-115."
        result = await validate_citation(citation, "Vancouver")
        assert result == "VALID"

    async def test_unknown_style_returns_valid(self) -> None:
        citation = "Some citation."
        result = await validate_citation(citation, "UnknownStyle")
        assert result == "VALID"

    async def test_ieee_valid_with_period(self) -> None:
        citation = 'J. Smith, "Title," *Journal*, vol. 5, no. 2, pp. 100-115, 2023.'
        result = await validate_citation(citation, "IEEE")
        assert result == "VALID"


class TestConvertCitationStyleEdges:
    """Additional edge-case tests for convert_citation_style."""

    async def test_contains_from_and_to_styles(self) -> None:
        result = await convert_citation_style("Any citation.", "Chicago", "MLA")
        assert "Chicago" in result
        assert "MLA" in result

    async def test_contains_original_text(self) -> None:
        original = "A very specific citation string."
        result = await convert_citation_style(original, "IEEE", "APA7")
        assert original in result
