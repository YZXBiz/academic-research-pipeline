"""Tests for the updated _RUBRIC_SECTION_DRAFT and the _build_traceability_context helper."""
from __future__ import annotations


def test_rubric_includes_numerical_traceability_dimension() -> None:
    from academic_pipeline.writing.graph import _RUBRIC_SECTION_DRAFT
    assert "Numerical traceability" in _RUBRIC_SECTION_DRAFT


def test_rubric_includes_placeholder_hygiene_dimension() -> None:
    from academic_pipeline.writing.graph import _RUBRIC_SECTION_DRAFT
    assert "Placeholder hygiene" in _RUBRIC_SECTION_DRAFT


def test_rubric_mentions_pending_marker_convention() -> None:
    """Rubric must tell the evaluator that [PENDING:...] is the valid defer pattern."""
    from academic_pipeline.writing.graph import _RUBRIC_SECTION_DRAFT
    assert "[PENDING:" in _RUBRIC_SECTION_DRAFT


def test_rubric_mentions_hedge_language_non_excuse() -> None:
    """Rubric must explicitly state hedge language doesn't excuse invented numbers."""
    from academic_pipeline.writing.graph import _RUBRIC_SECTION_DRAFT
    text = _RUBRIC_SECTION_DRAFT.lower()
    assert "interim" in text or "preliminary" in text
    assert "hedge" in text or "does not excuse" in text or "does NOT excuse" in _RUBRIC_SECTION_DRAFT


def test_rubric_lists_forbidden_placeholder_patterns() -> None:
    from academic_pipeline.writing.graph import _RUBRIC_SECTION_DRAFT
    # Must mention at least PROSPERO and TBD style patterns
    assert "CRD42024-XXXXXX" in _RUBRIC_SECTION_DRAFT or "XXXX" in _RUBRIC_SECTION_DRAFT
    assert "TBD" in _RUBRIC_SECTION_DRAFT


def test_build_traceability_context_empty_state() -> None:
    """When no upstream artifacts are present, returns empty string."""
    from academic_pipeline.writing.graph import _build_traceability_context
    from academic_pipeline.writing.state import WritingState

    state = WritingState(topic="t")
    out = _build_traceability_context(state)
    assert out == ""


def test_build_traceability_context_includes_synthesis() -> None:
    """When synthesis is present, output contains a SYNTHESIS section."""
    from academic_pipeline.writing.graph import _build_traceability_context
    from academic_pipeline.writing.state import WritingState

    state = WritingState(topic="t")
    # Use a string-typed synthesis (the real schema uses a Pydantic model but a
    # plain object with model_dump_json is enough to test plumbing).
    state.synthesis = type(  # type: ignore[assignment]
        "FakeSynthesis", (), {
            "model_dump_json": lambda self, indent=None: '{"hypothesis":"x"}',
        },
    )()

    out = _build_traceability_context(state)
    assert "SYNTHESIS" in out
    assert "hypothesis" in out


def test_section_writer_yaml_includes_anti_fabrication_section() -> None:
    """The section_writer.yaml instructions must include the anti-fabrication block."""
    from pathlib import Path
    yaml_path = Path("src/academic_pipeline/writing/specs/section_writer.yaml")
    text = yaml_path.read_text()
    assert "Anti-Fabrication Rules" in text
    assert "[PENDING:" in text
    assert "CRD42024-XXXXXX" in text
    assert "Effect sizes" in text
    assert "Heterogeneity statistics" in text
    assert "Registration ID Rule" in text


def test_section_writer_yaml_loads_via_pydantic_ai() -> None:
    """The YAML must remain a valid PydanticAI agent spec."""
    from academic_pipeline.runtime.model_registry import build_agent
    agent = build_agent(
        "section_writer",
        "src/academic_pipeline/writing/specs/section_writer.yaml",
    )
    assert agent is not None
