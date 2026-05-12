"""Tests for BibTeX generator tools."""

from __future__ import annotations

from academic_pipeline.tools.bibliography.bibtex import (
    _escape_bibtex,
    _make_citation_key,
    generate_bibtex_entry,
    generate_bibtex_file,
)


class TestGenerateBibtexEntry:
    """Tests for generate_bibtex_entry."""

    def test_journal_article(self) -> None:
        """Full metadata produces a valid @article entry with all fields."""
        metadata: dict[str, object] = {
            "authors": ["Vaswani, Ashish", "Shazeer, Noam"],
            "title": "Attention Is All You Need",
            "year": 2017,
            "journal": "Advances in Neural Information Processing Systems",
            "volume": "30",
            "number": "1",
            "pages": "5998-6008",
            "doi": "10.5555/3295222.3295349",
            "publisher": "Curran Associates",
        }
        result = generate_bibtex_entry(metadata)

        assert result.startswith("@article{vaswani2017,")
        assert "author = {Vaswani, Ashish and Shazeer, Noam}," in result
        assert "title = {Attention Is All You Need}," in result
        assert "year = {2017}," in result
        assert "journal = {Advances in Neural Information Processing Systems}," in result
        assert "volume = {30}," in result
        assert "number = {1}," in result
        assert "pages = {5998-6008}," in result
        assert "doi = {10.5555/3295222.3295349}," in result
        assert "publisher = {Curran Associates}," in result
        assert result.endswith("}")

    def test_missing_fields_still_generates(self) -> None:
        """Minimal metadata (title, authors, year) still produces a valid entry."""
        metadata: dict[str, object] = {
            "authors": ["Smith, John"],
            "title": "A Short Paper",
            "year": 2023,
        }
        result = generate_bibtex_entry(metadata)

        assert result.startswith("@article{smith2023,")
        assert "title = {A Short Paper}," in result
        assert "year = {2023}," in result
        # Fields with no value should be omitted
        assert "journal" not in result
        assert "volume" not in result
        assert "doi" not in result

    def test_citation_key_format(self) -> None:
        """Citation key is lowercase surname + year."""
        metadata: dict[str, object] = {
            "authors": ["Einstein, Albert"],
            "title": "Relativity",
            "year": 1905,
        }
        result = generate_bibtex_entry(metadata)
        assert result.startswith("@article{einstein1905,")

    def test_special_characters_escaped(self) -> None:
        """& and other LaTeX special characters are escaped."""
        metadata: dict[str, object] = {
            "authors": ["O'Brien, Pat"],
            "title": "Costs & Benefits of A_B Testing in C# and 50% Savings",
            "year": 2024,
            "journal": "R&D Journal",
        }
        result = generate_bibtex_entry(metadata)

        assert r"Costs \& Benefits of A\_B Testing in C\# and 50\% Savings" in result
        assert r"R\&D Journal" in result


class TestGenerateBibtexFile:
    """Tests for generate_bibtex_file."""

    def test_multiple_entries(self) -> None:
        """Two metadata dicts produce two @article blocks separated by blank line."""
        entries: list[dict[str, object]] = [
            {"authors": ["Alpha, A"], "title": "Paper One", "year": 2020},
            {"authors": ["Beta, B"], "title": "Paper Two", "year": 2021},
        ]
        result = generate_bibtex_file(entries)

        assert result.count("@article{") == 2
        # Entries are separated by a double newline
        assert "\n\n@article{" in result

    def test_empty_list(self) -> None:
        """Empty input list returns empty string."""
        assert generate_bibtex_file([]) == ""


class TestHelpers:
    """Tests for internal helper functions."""

    def test_escape_bibtex_all_special(self) -> None:
        assert _escape_bibtex("a & b % c # d _ e") == r"a \& b \% c \# d \_ e"

    def test_escape_bibtex_no_special(self) -> None:
        assert _escape_bibtex("plain text") == "plain text"

    def test_make_citation_key_family_given(self) -> None:
        key = _make_citation_key({"authors": ["Doe, Jane"], "year": 2022})
        assert key == "doe2022"

    def test_make_citation_key_no_author(self) -> None:
        key = _make_citation_key({"title": "Anonymous", "year": 2000})
        assert key == "unknown2000"

    def test_make_citation_key_given_family_format(self) -> None:
        """Handle 'Given Family' format (no comma)."""
        key = _make_citation_key({"authors": ["Jane Doe"], "year": 2022})
        assert key == "doe2022"


class TestBibtexKeyFromSourceId:
    """BibTeX entry key should use Source.id when provided."""

    def test_uses_source_id_when_provided(self) -> None:
        entry: dict[str, object] = {
            "id": "sculley2015",
            "title": "Hidden Debt",
            "authors": ["Sculley, D."],
            "year": "2015",
        }
        bibtex = generate_bibtex_entry(entry)
        assert "@article{sculley2015," in bibtex

    def test_falls_back_to_generated_key_without_id(self) -> None:
        entry: dict[str, object] = {
            "title": "Some Paper",
            "authors": ["Jones, A."],
            "year": "2022",
        }
        bibtex = generate_bibtex_entry(entry)
        assert "@article{jones2022," in bibtex

    def test_id_matches_across_file(self) -> None:
        entries: list[dict[str, object]] = [
            {"id": "breck2017", "title": "ML Test Score", "authors": ["Breck, E."], "year": "2017"},
            {"id": "sculley2015", "title": "Hidden Debt", "authors": ["Sculley, D."], "year": "2015"},
        ]
        bib = generate_bibtex_file(entries)
        assert "@article{breck2017," in bib
        assert "@article{sculley2015," in bib
