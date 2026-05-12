"""Tests for schema validation helpers."""

from __future__ import annotations

import logging

from academic_pipeline.research.state import ResearchState
from academic_pipeline.runtime.validators import validate_state
from tests.unit.core.test_serialization import _make_bibliography, _make_rq_brief


class TestValidateState:
    def test_passes_when_required_fields_present(self) -> None:
        state = ResearchState(rq_brief=_make_rq_brief(), bibliography=_make_bibliography())
        validate_state(state, required=["rq_brief", "bibliography"], node_name="TestNode")

    def test_warns_when_field_is_none(self, caplog: logging.LogRecordArgs) -> None:
        state = ResearchState()
        with caplog.at_level(logging.WARNING):  # type: ignore[union-attr]
            validate_state(state, required=["bibliography"], node_name="TestNode")
        assert "Required state field 'bibliography' is None" in caplog.text

    def test_warns_with_node_name_in_message(self, caplog: logging.LogRecordArgs) -> None:
        state = ResearchState()
        with caplog.at_level(logging.WARNING):  # type: ignore[union-attr]
            validate_state(state, required=["bibliography"], node_name="SynthesisNode")
        assert "[SynthesisNode]" in caplog.text

    def test_passes_with_empty_required_list(self) -> None:
        state = ResearchState()
        validate_state(state, required=[], node_name="TestNode")
