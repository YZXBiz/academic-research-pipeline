"""Tests for IntegrityState dataclass."""

from __future__ import annotations

from academic_pipeline.integrity.state import IntegrityState
from academic_pipeline.models.shared import (
    Author,
    Reference,
)
from academic_pipeline.models.writing import (
    PaperDraft,
    Section,
)


def _make_paper_draft() -> PaperDraft:
    return PaperDraft(
        title="Test",
        abstract="Test abstract",
        authors=[Author(name="Smith", affiliation="MIT")],
        keywords=["a", "b", "c"],
        sections=[Section(heading="Intro", level=1, content="Test paper content", word_count=50, citation_count=1)],
        references=[Reference(id="r1", full_citation="Smith (2024)")],
        total_word_count=50,
    )


class TestIntegrityState:
    def test_default_construction(self) -> None:
        state = IntegrityState()
        assert state.paper_draft is None
        assert state.integrity_report == {}
        assert state.integrity_phase == ""
        assert state.messages == []

    def test_construction_with_values(self) -> None:
        draft = _make_paper_draft()
        state = IntegrityState(
            paper_draft=draft,
            integrity_report={"verdict": "PASS", "raw": "ok"},
            integrity_phase="pre",
        )
        assert state.paper_draft is not None
        assert state.paper_draft.title == "Test"
        assert state.integrity_report["verdict"] == "PASS"
        assert state.integrity_phase == "pre"

    def test_messages_are_independent_per_instance(self) -> None:
        s1 = IntegrityState()
        s2 = IntegrityState()
        s1.messages.append({"role": "system", "content": "hello"})
        assert s2.messages == []

    # PRD §6.5.T1 — checklist ethics moves to integrity subgraph.

    def test_ethics_checklist_field_exists_and_defaults_to_none(self) -> None:
        """PRD §6.5.T1 — IntegrityState gains an ethics_checklist field
        (typed `EthicsChecklist | None`, default None) populated by the new
        EthicsChecklistNode."""
        state = IntegrityState()
        assert hasattr(state, "ethics_checklist"), "IntegrityState must expose `ethics_checklist` after PRD §6.5.T1"
        assert state.ethics_checklist is None

    def test_ethics_checklist_field_accepts_ethics_checklist_instance(self) -> None:
        """The field must round-trip through dataclass construction with a
        real EthicsChecklist value."""
        from academic_pipeline.models.ethics import (
            STANDARD_ITEMS,
            ChecklistItem,
            EthicsChecklist,
        )

        items = [
            ChecklistItem(
                name=name,
                answer=True,
                justification=f"Justification text for {name} (>= 20 chars).",
                waiver=None,
            )
            for name in STANDARD_ITEMS
        ]
        checklist = EthicsChecklist(items=items, blocker_items=[], overall_verdict="pass")
        state = IntegrityState(ethics_checklist=checklist)
        assert state.ethics_checklist is checklist
        assert state.ethics_checklist.overall_verdict == "pass"
