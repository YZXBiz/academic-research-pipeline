"""State dataclass for the integrity subgraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Runtime imports — pydantic-graph snapshot serialization needs these at
# runtime; moving them under TYPE_CHECKING breaks resume.
from academic_pipeline.models.ethics import EthicsChecklist  # noqa: TCH001
from academic_pipeline.models.integrity import ComplianceReport  # noqa: TCH001
from academic_pipeline.models.writing import PaperDraft  # noqa: TCH001


@dataclass
class IntegrityState:
    """State for the integrity verification subgraph."""

    paper_draft: PaperDraft | None = None
    integrity_report: dict[str, Any] = field(default_factory=dict)
    integrity_phase: str = ""
    failure_mode_results: dict[str, Any] = field(default_factory=dict)  # TODO: populate from agent output
    messages: list[dict[str, str]] = field(default_factory=list)
    compliance_stage: Literal["2.5", "4.5"] = "2.5"
    compliance_report: ComplianceReport | None = None
    # PRD §6.5.T1 — Spec 8 checklist ethics. Populated by EthicsChecklistNode
    # in `integrity/graph.py` when `config.ethics_checklist_enabled=True`.
    # Replaces the legacy freeform research-side EthicsReviewNode (deleted
    # in §6.1.T6 once this path is verified end-to-end).
    ethics_checklist: EthicsChecklist | None = None
