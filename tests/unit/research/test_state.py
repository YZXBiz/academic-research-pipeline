"""Tests for ResearchState dataclass."""

from __future__ import annotations

from academic_pipeline.research.state import ResearchState
from academic_pipeline.core.enums import Verdict
from tests.unit.core.test_serialization import (
    _make_bibliography,
    _make_rq_brief,
    _make_synthesis,
)


class TestResearchState:
    def test_default_construction(self) -> None:
        state = ResearchState()
        assert state.topic == ""
        assert state.rq_brief is None
        assert state.methodology_blueprint is None
        assert state.bibliography is None
        assert state.synthesis is None
        assert state.review_report == {}
        assert state.monitoring_config == {}
        assert state.messages == []
        assert state.needs_revision is False
        assert state.eic_review == ""
        assert state.ethics_verdict is None

    def test_ethics_verdict_accepts_enum(self) -> None:
        state = ResearchState(ethics_verdict=Verdict.CLEARED)
        assert state.ethics_verdict == Verdict.CLEARED

    def test_messages_independent(self) -> None:
        s1 = ResearchState()
        s2 = ResearchState()
        s1.messages.append({"role": "user", "content": "hi"})
        assert s2.messages == []

    def test_mutable_defaults_independent(self) -> None:
        s1 = ResearchState()
        s2 = ResearchState()
        s1.review_report["key"] = "value"
        s1.monitoring_config["key"] = "value"
        assert s2.review_report == {}
        assert s2.monitoring_config == {}

    def test_construction_with_all_fields(self) -> None:
        rq = _make_rq_brief()
        bib = _make_bibliography()
        syn = _make_synthesis()
        state = ResearchState(
            topic="quantum computing",
            rq_brief=rq,
            bibliography=bib,
            synthesis=syn,
            review_report={"score": 8},
            monitoring_config={"interval": 60},
            messages=[{"role": "system", "content": "init"}],
            needs_revision=True,
            eic_review="minor revisions needed",
            ethics_verdict=Verdict.CLEARED,
        )
        assert state.topic == "quantum computing"
        assert state.synthesis is not None
        assert len(state.synthesis.themes) == 3
        assert state.needs_revision is True
        assert state.eic_review == "minor revisions needed"


class TestResearchStateRevisionFields:
    def test_has_eic_review_structured_field(self) -> None:
        state = ResearchState(topic="test")
        assert state.eic_review_structured is None
