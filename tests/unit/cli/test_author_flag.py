"""Tests for the --author CLI flag parser."""

from __future__ import annotations

from academic_pipeline.cli import _parse_authors


class TestParseAuthors:
    def test_empty_returns_empty_list(self) -> None:
        assert _parse_authors(None) == []
        assert _parse_authors([]) == []

    def test_single_author_name_only(self) -> None:
        assert _parse_authors(["Jane Doe"]) == [
            {"name": "Jane Doe", "affiliation": ""}
        ]

    def test_single_author_with_affiliation(self) -> None:
        assert _parse_authors(["Jane Doe | MIT"]) == [
            {"name": "Jane Doe", "affiliation": "MIT"}
        ]

    def test_single_author_with_email(self) -> None:
        assert _parse_authors(["Jane Doe | MIT | jane@mit.edu"]) == [
            {"name": "Jane Doe", "affiliation": "MIT", "email": "jane@mit.edu"}
        ]

    def test_multiple_authors(self) -> None:
        result = _parse_authors([
            "Jackson Yang | Example Institute | jackson@example.com",
            "Co Author | Other Lab",
        ])
        assert len(result) == 2
        assert result[0]["name"] == "Jackson Yang"
        assert result[0]["affiliation"] == "Example Institute"
        assert result[0]["email"] == "jackson@example.com"
        assert result[1]["name"] == "Co Author"
        assert result[1]["affiliation"] == "Other Lab"
        assert "email" not in result[1]

    def test_strips_whitespace(self) -> None:
        result = _parse_authors(["  Name  |  Affil  |  email@x.com  "])
        assert result[0]["name"] == "Name"
        assert result[0]["affiliation"] == "Affil"
        assert result[0]["email"] == "email@x.com"
