"""Tests for bibliography-aware citation resolution."""

from __future__ import annotations

from academic_pipeline.runtime.citation_resolver import (
    extract_cite_tokens,
    resolve_citations_to_cite_commands,
    resolve_citations_to_numbers,
)


REF_MAP = {
    "wolpert1996nfl": 1,
    "alaa2019cvdukbiobank": 2,
    "thirunavukarasu2024autoML": 3,
    "van-leeuwen2025": 4,
    "foo_bar2020": 5,
    "smith2020": 6,
}


class TestResolveToCiteCommands:
    def test_known_key_converted(self) -> None:
        assert resolve_citations_to_cite_commands("[wolpert1996nfl]", REF_MAP) == r"\cite{wolpert1996nfl}"

    def test_unknown_key_left_alone(self) -> None:
        assert resolve_citations_to_cite_commands("[zzz9999]", REF_MAP) == "[zzz9999]"

    def test_clinical_trial_id_left_alone(self) -> None:
        assert resolve_citations_to_cite_commands("[NCT04567890]", REF_MAP) == "[NCT04567890]"

    def test_cve_id_left_alone(self) -> None:
        assert resolve_citations_to_cite_commands("[CVE-2024-1234]", REF_MAP) == "[CVE-2024-1234]"

    def test_numbered_ref_left_alone(self) -> None:
        assert resolve_citations_to_cite_commands("[1]", REF_MAP) == "[1]"

    def test_roman_numeral_left_alone(self) -> None:
        assert resolve_citations_to_cite_commands("see Section [IV]", REF_MAP) == "see Section [IV]"

    def test_multi_letter_uppercase_in_suffix(self) -> None:
        assert resolve_citations_to_cite_commands(
            "[thirunavukarasu2024autoML]", REF_MAP
        ) == r"\cite{thirunavukarasu2024autoML}"

    def test_underscore_in_key_preserved(self) -> None:
        assert resolve_citations_to_cite_commands("[foo_bar2020]", REF_MAP) == r"\cite{foo_bar2020}"

    def test_hyphen_in_key_preserved(self) -> None:
        assert resolve_citations_to_cite_commands("[van-leeuwen2025]", REF_MAP) == r"\cite{van-leeuwen2025}"

    def test_adjacent_citations_merged(self) -> None:
        assert resolve_citations_to_cite_commands(
            "[wolpert1996nfl][smith2020]", REF_MAP
        ) == r"\cite{wolpert1996nfl,smith2020}"

    def test_spaced_adjacent_citations_merged(self) -> None:
        assert resolve_citations_to_cite_commands(
            "[wolpert1996nfl] [smith2020]", REF_MAP
        ) == r"\cite{wolpert1996nfl,smith2020}"

    def test_mixed_known_and_unknown_in_adjacent(self) -> None:
        # Adjacent merge only when BOTH keys are known
        result = resolve_citations_to_cite_commands(
            "[wolpert1996nfl][NCT04567890]", REF_MAP
        )
        assert result == r"\cite{wolpert1996nfl}[NCT04567890]"

    def test_narrative_citation(self) -> None:
        assert resolve_citations_to_cite_commands(
            "Wolpert [wolpert1996nfl] argues...", REF_MAP
        ) == r"Wolpert \cite{wolpert1996nfl} argues..."

    def test_yearless_known_key_converted(self) -> None:
        """A bib key without a year is still a citation if it's in ref_map (contract: iff in ref_map)."""
        assert resolve_citations_to_cite_commands(
            "[darwin]", {"darwin": 1, **REF_MAP}
        ) == r"\cite{darwin}"

    def test_spaced_comma_in_keys(self) -> None:
        assert resolve_citations_to_cite_commands(
            "[wolpert1996nfl, smith2020]", REF_MAP
        ) == r"\cite{wolpert1996nfl,smith2020}"


class TestResolveToNumbers:
    def test_known_key_to_number(self) -> None:
        assert resolve_citations_to_numbers("[wolpert1996nfl]", REF_MAP) == "[1]"

    def test_unknown_key_left_alone(self) -> None:
        assert resolve_citations_to_numbers("[zzz9999]", REF_MAP) == "[zzz9999]"

    def test_adjacent_known_merged_to_number_list(self) -> None:
        assert resolve_citations_to_numbers(
            "[wolpert1996nfl][smith2020]", REF_MAP
        ) == "[1, 6]"

    def test_already_numbered_left_alone(self) -> None:
        assert resolve_citations_to_numbers("[1]", REF_MAP) == "[1]"

    def test_spaced_comma_to_numbers(self) -> None:
        assert resolve_citations_to_numbers(
            "[wolpert1996nfl, smith2020]", REF_MAP
        ) == "[1, 6]"


class TestExtractTokens:
    def test_finds_all_bracket_tokens(self) -> None:
        tokens = extract_cite_tokens("text [a] more [b,c] end [1] [d]")
        # numeric tokens excluded; non-year tokens excluded
        assert tokens == []

    def test_finds_year_tokens(self) -> None:
        tokens = extract_cite_tokens("see [smith2020] and [jones2021,doe2022]")
        assert tokens == ["smith2020", "jones2021", "doe2022"]


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert resolve_citations_to_cite_commands("", REF_MAP) == ""
        assert extract_cite_tokens("") == []

    def test_unclosed_bracket(self) -> None:
        # Should not crash; should leave text alone
        assert resolve_citations_to_cite_commands("text [unclosed", REF_MAP) == "text [unclosed"

    def test_empty_brackets(self) -> None:
        # Empty body — neither known nor matchable
        assert resolve_citations_to_cite_commands("text []", REF_MAP) == "text []"
