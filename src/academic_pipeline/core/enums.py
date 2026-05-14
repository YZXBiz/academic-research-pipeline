"""StrEnum types for pipeline stages, statuses, and routing outcomes."""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """Sequential pipeline stages from research through finalization."""

    RESEARCH = "research"
    WRITE = "write"
    EXPERIMENT = "experiment"
    PRE_INTEGRITY = "pre_integrity"
    REVIEW = "review"
    FINAL_INTEGRITY = "final_integrity"
    FINALIZE = "finalize"
    SUMMARY = "summary"


# Numbered output-directory prefix for each dir-producing stage. Single source
# of truth — agent `phase=` args and `output/<run>/NN-name/` paths must use
# these, never inline literals. run-0514 had `02-experiment` and `02-writing`
# collide because the experiment phase was added without renumbering;
# tests/unit/core/test_phase_dirs.py guards against that recurring.
# FINALIZE/SUMMARY finish the run and write no numbered phase dir of their own.
PHASE_DIRS: dict[Stage, str] = {
    Stage.RESEARCH: "01-research",
    Stage.EXPERIMENT: "02-experiment",
    Stage.WRITE: "03-writing",
    Stage.PRE_INTEGRITY: "04-integrity",
    Stage.REVIEW: "05-review",
    Stage.FINAL_INTEGRITY: "06-final",
}


class PipelineStatus(StrEnum):
    """Top-level lifecycle status of the pipeline run."""

    INITIALIZING = "initializing"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"


class StageStatus(StrEnum):
    """Execution status of an individual pipeline stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class CheckpointType(StrEnum):
    """Checkpoint granularity for pipeline state persistence."""

    FULL = "FULL"
    SLIM = "SLIM"
    MANDATORY = "MANDATORY"


class AgentType(StrEnum):
    """Agent role identifiers used for routing and logging."""

    RESEARCH = "research"
    WRITING = "writing"
    REVIEW = "review"
    INTEGRITY = "integrity"


class Verdict(StrEnum):
    """Quality gate verdicts issued by review and integrity agents."""

    PASS = "PASS"
    PASS_WITH_CONDITIONS = "PASS_WITH_CONDITIONS"
    REVISE = "REVISE"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    CLEARED = "CLEARED"


class EditorialDecision(StrEnum):
    """Editor-in-chief decisions following peer review."""

    ACCEPT = "Accept"
    MINOR_REVISION = "Minor Revision"
    MAJOR_REVISION = "Major Revision"
    REJECT = "Reject"

    @classmethod
    def from_label(cls, label: str) -> EditorialDecision:
        """Map a lowercase decision label to the enum value."""
        _map = {v.value.lower(): v for v in cls}
        return _map.get(label.lower(), cls.MAJOR_REVISION)


class ReviewDimension(StrEnum):
    """Dimensions scored by the editor-in-chief and referenced by DA issues."""

    ORIGINALITY = "originality"
    METHODOLOGY = "methodology"
    EVIDENCE = "evidence"
    COHERENCE = "coherence"
    WRITING = "writing"


class IssueSeverity(StrEnum):
    """Severity levels for review issues (editor and DA agents)."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    SUGGESTION = "suggestion"


SEVERITY_RANK: dict[str, int] = {s.value: i for i, s in enumerate(IssueSeverity)}


class RevisionSource(StrEnum):
    """Source of a revision request."""

    EDITOR_IN_CHIEF = "editor_in_chief"
