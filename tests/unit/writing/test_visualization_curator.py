"""visualization.yaml must describe the curator role + skip python code generation.

Uses yaml.safe_load to inspect the parsed spec rather than substring search,
so comments / disabled code don't false-pass.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _spec() -> dict:
    raw = Path("src/academic_pipeline/writing/specs/visualization.yaml").read_text()
    return yaml.safe_load(raw)


def test_visualization_yaml_no_longer_requests_python_code() -> None:
    """Sandbox figure exec was retired; asking for python_code wastes
    tokens AND can re-introduce the broken sandbox path."""
    instructions = _spec()["instructions"].lower()
    # Field name to NOT request (the new Figure model has both `code` and `source_path`;
    # we want the curator to fill source_path, not code).
    assert "python code" not in instructions, (
        "visualization.yaml must not request python code generation — "
        "figures come from state.experiment_figures (Dagster workspace PNGs)."
    )


def test_visualization_yaml_describes_curator_role() -> None:
    instructions = _spec()["instructions"].lower()
    assert "curator" in instructions or "curat" in instructions, (
        "Spec must describe the curator role explicitly so the agent picks "
        "from inventory instead of inventing figures."
    )
    assert "source_path" in instructions, (
        "Spec must reference the source_path field the agent populates."
    )
    assert "available_figures" in instructions, (
        "Spec must reference the available_figures inventory label "
        "(matches what VisualizationNode injects into context)."
    )


def test_visualization_yaml_max_tokens_high_enough_for_thinking() -> None:
    """Per commit d3c6844: Thinking xhigh consumes most of max_tokens before
    structured output. 16K is too tight; project convention is 32K-128K."""
    spec = _spec()
    max_tokens = spec.get("model_settings", {}).get("max_tokens", 0)
    assert max_tokens >= 32000, (
        f"max_tokens={max_tokens} too low. Thinking xhigh consumes most "
        f"of the budget before structured output begins. Use >=32000."
    )
