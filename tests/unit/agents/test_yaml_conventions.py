"""Repo-wide conventions for agent YAML specs.

Regression: run-0504-1212_cf0d crashed because three Spec 7 YAMLs
(experiment_designer_bundle, design_scorer, design_comparator) didn't set
`model_settings.max_tokens`. PydanticAI defaults that to 4096 when omitted.
With `Thinking: xhigh` enabled, thinking tokens consume most of that budget,
leaving ~1500 tokens for actual structured output. The bundle agent had to
fit four full ExperimentPlans in one response and got truncated mid-JSON
(EOF at column 9817), failing PydanticAI's validation. PydanticAI retried
and the model produced the same overflow each time, exhausting `output_retries`.

The real invariant: every spec that uses `Thinking` MUST set an explicit
`model_settings.max_tokens` (project convention is 128000) so thinking
budget plus output budget can both fit. Validating that here prevents the
exact "thinking eats output budget → JSON truncated → infinite retry death"
class of bug from recurring.

`output_retries` is also asserted because PydanticAI's default of 1 attempt
is too brittle for any structured output.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SPECS_GLOB = "src/academic_pipeline/*/specs/*.yaml"

_SPEC_FILES = sorted(REPO_ROOT.glob(SPECS_GLOB))


def _agent_specs() -> list[Path]:
    """Return YAML files that look like agent specs (have an `instructions` block)."""
    out: list[Path] = []
    for path in _SPEC_FILES:
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "instructions" in data:
            out.append(path)
    return out


def _has_thinking(data: dict) -> bool:
    """Return True if the spec declares the Thinking capability."""
    caps = data.get("capabilities") or []
    for cap in caps:
        if cap == "Thinking":
            return True
        if isinstance(cap, dict) and "Thinking" in cap:
            return True
    return False


@pytest.mark.parametrize("spec_path", _agent_specs(), ids=lambda p: p.name)
def test_thinking_specs_set_max_tokens(spec_path: Path) -> None:
    """Specs with Thinking enabled MUST set model_settings.max_tokens.

    Without explicit max_tokens, PydanticAI uses the provider default (4096
    for Anthropic). Thinking tokens are charged against this budget, so the
    actual output budget can drop to ~1500 tokens — far short of what nested
    structured outputs need. Run-0504-1212_cf0d crashed exactly this way.
    """
    data = yaml.safe_load(spec_path.read_text())
    assert isinstance(data, dict), f"{spec_path.name} did not parse as a dict"
    if not _has_thinking(data):
        pytest.skip(f"{spec_path.name} has no Thinking capability")
    settings = data.get("model_settings") or {}
    max_tokens = settings.get("max_tokens")
    assert isinstance(max_tokens, int) and max_tokens >= 8000, (
        f"{spec_path.name} uses Thinking but has model_settings.max_tokens="
        f"{max_tokens!r}. Thinking tokens count against max_tokens, so the "
        "default of 4096 leaves only ~1500 tokens for structured output and "
        "causes mid-JSON truncation. Set model_settings.max_tokens to at "
        "least 8000 (project convention is 128000)."
    )


@pytest.mark.parametrize("spec_path", _agent_specs(), ids=lambda p: p.name)
def test_spec_declares_output_retries(spec_path: Path) -> None:
    """Every agent spec must set output_retries (>=1).

    Defaulting to PydanticAI's 1 attempt means the first malformed structured
    output crashes the entire pipeline — fragile for any non-trivial schema.
    """
    data = yaml.safe_load(spec_path.read_text())
    assert isinstance(data, dict), f"{spec_path.name} did not parse as a dict"
    assert "output_retries" in data, (
        f"{spec_path.name} is missing `output_retries` — add it to the YAML so "
        "validation failures are retried instead of crashing the pipeline."
    )
    value = data["output_retries"]
    assert isinstance(value, int) and value >= 1, (
        f"{spec_path.name} has output_retries={value!r}; expected a positive integer."
    )


def test_spec_files_discovered() -> None:
    """Sanity check that the glob actually finds specs (catches refactor drift)."""
    specs = _agent_specs()
    assert len(specs) >= 40, (
        f"Only found {len(specs)} agent specs under {SPECS_GLOB}; "
        "did the directory layout change?"
    )
