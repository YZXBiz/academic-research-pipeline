"""Tests for the §6.7.T4 formatter title-12-word gate.

Per PRD §6.7.T4 + §17:
- The formatter agent has an ``output_validator`` that rejects manuscripts
  with ``title.split() > 12`` words.
- Rejection raises ``ModelRetry`` so PydanticAI re-prompts the model
  (one revision attempt = ``output_retries=1``).
- Error code ``REN003`` per the REN namespace.
- Title lives in ``FormattedPaper.metadata["title"]``.
"""

from __future__ import annotations

import pytest


_LONG_TITLE = (
    "When No Algorithm Wins A Multi Layer Benchmark of K means "
    "Hierarchical DBSCAN and GMM Clustering for Pharmacy Store Segmentation "
    "Reveals Index Actionability Divergence"
)
_SHORT_TITLE = "Large Language Models Enable Few-Shot Clustering"  # 6 words


class TestRenderingErrorsRen003:
    def test_title_too_long_error_carries_ren003(self) -> None:
        from academic_pipeline.runtime.rendering_errors import TitleTooLongError

        err = TitleTooLongError(title="some long title here", word_count=15)
        assert err.error_code == "REN003"
        assert "15" in str(err)
        assert "12" in str(err)


class TestValidateFormatterTitle:
    """``writing/agents.py::validate_formatter_title`` is the actual validator."""

    def test_short_title_passes_through_unchanged(self) -> None:
        from academic_pipeline.models.writing import FormattedPaper
        from academic_pipeline.writing.agents import validate_formatter_title

        paper = FormattedPaper(
            formatted_content="...",
            format_type="LaTeX",
            metadata={"title": _SHORT_TITLE},
        )
        # Validator returns the same object on the happy path.
        assert validate_formatter_title(paper) is paper

    def test_long_title_raises_model_retry_with_ren003(self) -> None:
        from pydantic_ai import ModelRetry

        from academic_pipeline.models.writing import FormattedPaper
        from academic_pipeline.writing.agents import validate_formatter_title

        paper = FormattedPaper(
            formatted_content="...",
            format_type="LaTeX",
            metadata={"title": _LONG_TITLE},
        )

        with pytest.raises(ModelRetry) as exc:
            validate_formatter_title(paper)
        # Message must mention REN003 + the constraint so the model self-corrects.
        msg = str(exc.value)
        assert "REN003" in msg
        assert "12" in msg
        assert "word" in msg.lower()

    def test_exactly_12_words_passes(self) -> None:
        from academic_pipeline.models.writing import FormattedPaper
        from academic_pipeline.writing.agents import validate_formatter_title

        title_12 = "one two three four five six seven eight nine ten eleven twelve"
        paper = FormattedPaper(
            formatted_content="...",
            format_type="LaTeX",
            metadata={"title": title_12},
        )
        assert validate_formatter_title(paper) is paper

    def test_thirteen_words_fails(self) -> None:
        from pydantic_ai import ModelRetry

        from academic_pipeline.models.writing import FormattedPaper
        from academic_pipeline.writing.agents import validate_formatter_title

        title_13 = "one two three four five six seven eight nine ten eleven twelve thirteen"
        paper = FormattedPaper(
            formatted_content="...",
            format_type="LaTeX",
            metadata={"title": title_13},
        )
        with pytest.raises(ModelRetry):
            validate_formatter_title(paper)

    def test_missing_title_metadata_passes_through(self) -> None:
        """The validator MUST NOT crash when metadata has no 'title' key —
        production runs sometimes ship metadata without an explicit title
        (the LaTeX has \\title{} elsewhere)."""
        from academic_pipeline.models.writing import FormattedPaper
        from academic_pipeline.writing.agents import validate_formatter_title

        paper = FormattedPaper(
            formatted_content="...",
            format_type="LaTeX",
            metadata={},
        )
        # Pass-through is fine — there's no title to validate.
        assert validate_formatter_title(paper) is paper


class TestFormatterAgentWiring:
    """The formatter agent must have the validator + 1-revision retry budget."""

    def test_formatter_agent_has_title_validator_registered(self) -> None:
        """Inspect the agent's ``_output_validators`` to confirm the validator is wired.

        Catches accidental removal of the validator during refactors.
        """
        from academic_pipeline.writing.agents import agents, validate_formatter_title

        agent = agents["formatter"]
        # PydanticAI exposes registered output validators via _output_validators.
        validators = getattr(agent, "_output_validators", [])
        names = [getattr(getattr(v, "function", v), "__name__", "") for v in validators]
        assert (
            "validate_formatter_title" in names
        ), f"formatter agent must have validate_formatter_title attached. Got: {names}"
        # And the function reference matches.
        funcs = [getattr(v, "function", v) for v in validators]
        assert validate_formatter_title in funcs

    def test_formatter_yaml_pins_output_retries_to_one(self) -> None:
        """PRD §6.7.T4 - 'one revision attempt allowed'. Surface as
        output_retries: 1 so the second consecutive title-too-long failure
        promotes ModelRetry to UnexpectedModelBehavior and aborts cleanly.
        """
        from pathlib import Path

        import yaml

        spec_path = Path("src/academic_pipeline/writing/specs/formatter.yaml")
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        assert spec.get("output_retries") == 1, (
            "formatter.yaml must set output_retries: 1 per PRD §6.7.T4 " "('one revision attempt allowed')."
        )
