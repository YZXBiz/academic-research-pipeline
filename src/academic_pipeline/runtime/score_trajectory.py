"""Score trajectory tracking for revision round quality monitoring.

Pure utility functions for tracking review score deltas across
revision rounds, detecting regressions, and determining early-stop
convergence.

Per-thread persistence helpers (PRD §6.11.T1) write the score history
+ trajectory flags to ``<persistence_dir>/<thread_id>_scores.json`` so
the dashboard panel (§6.8.T2 in Phase 2) can render them without
loading the whole pipeline state. Pure functions; no global state.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path


logger = logging.getLogger(__name__)

DEFAULT_PERSISTENCE_DIR = Path(".pipeline_runs")

DIMENSIONS = [
    "argument_strength",
    "evidence_quality",
    "methodological_rigor",
    "writing_clarity",
    "citation_accuracy",
    "structural_coherence",
    "originality",
    "overall",
]

_LABEL_TO_SNAKE: dict[str, str] = {
    "argument strength": "argument_strength",
    "evidence quality": "evidence_quality",
    "methodological rigor": "methodological_rigor",
    "writing clarity": "writing_clarity",
    "citation accuracy": "citation_accuracy",
    "structural coherence": "structural_coherence",
    "originality": "originality",
    "overall": "overall",
}

# Matches lines like "Argument Strength: 75/100", "argument_strength: 75",
# "| Argument Strength | 75 |", "| argument_strength | 75/100 |"
_SCORE_PATTERNS: list[re.Pattern[str]] = [
    # Table row: | dimension | score |  or  | dimension | score/100 |
    re.compile(
        r"\|\s*(?P<dim>[A-Za-z][A-Za-z_ ]+?)\s*\|\s*(?P<score>\d{1,3})(?:\s*/\s*100)?\s*\|",
    ),
    # Key-value: dimension: score/100  or  dimension: score
    re.compile(
        r"(?P<dim>[A-Za-z][A-Za-z_ ]+?)\s*:\s*(?P<score>\d{1,3})(?:\s*/\s*100)?(?:\s|$)",
    ),
]


def _normalize_dimension(raw: str) -> str | None:
    """Normalize a raw dimension label to a snake_case DIMENSIONS key.

    Returns ``None`` if the label does not match any known dimension.
    """
    key = raw.strip().lower().replace("_", " ")
    snake = _LABEL_TO_SNAKE.get(key)
    if snake is not None:
        return snake
    # Try direct snake_case match
    direct = raw.strip().lower().replace(" ", "_")
    if direct in DIMENSIONS:
        return direct
    return None


def compute_deltas(current: dict[str, int], previous: dict[str, int]) -> dict[str, int]:
    """Compute per-dimension score deltas between two rounds.

    Args:
        current: Dimension -> score mapping for the current round.
        previous: Dimension -> score mapping for the previous round.

    Returns:
        Dict of dimension -> delta (current - previous) for each: dimension present in DIMENSIONS that appears in both
            inputs.
    """
    deltas: dict[str, int] = {}
    for dim in DIMENSIONS:
        if dim in current and dim in previous:
            deltas[dim] = current[dim] - previous[dim]
    return deltas


def detect_regression(deltas: dict[str, int], threshold: int = -3) -> list[str]:
    """Return dimension names where delta < threshold (regression detected).

    Args:
        deltas: Per-dimension score deltas from :func:`compute_deltas`.
        threshold: Negative delta value below which a dimension is flagged as regressing. Default ``-3`` means a drop of
            4+ points triggers a flag.

    Returns:
        List of dimension names that regressed beyond the threshold.
    """
    return [dim for dim, delta in deltas.items() if delta < threshold]


def check_early_stop(deltas: dict[str, int], threshold: int = 3, *, has_p0: bool = False) -> bool:
    """Return True if scores have converged and there are no P0 issues.

    Convergence means ALL deltas are below *threshold* (scores are not improving significantly) AND there are no
    critical (P0) issues.

    Args:
        deltas: Per-dimension score deltas from :func:`compute_deltas`.
        threshold: Maximum improvement delta below which scores are considered converged. Default ``3``.
        has_p0: Whether any P0 (critical) issues remain in the review.

    Returns:
        ``True`` when early-stop criteria are met.
    """
    if has_p0:
        return False
    if not deltas:
        return False
    return all(delta < threshold for delta in deltas.values())


def _scores_path(thread_id: str, persistence_dir: Path | None) -> Path:
    """Return the on-disk path for a thread's score-trajectory file."""
    base = persistence_dir if persistence_dir is not None else DEFAULT_PERSISTENCE_DIR
    return Path(base) / f"{thread_id}_scores.json"


def save_score_trajectory(
    *,
    thread_id: str,
    score_history: list[dict[str, int]],
    score_trajectory_flags: list[str],
    persistence_dir: Path | None = None,
) -> Path:
    """Persist a thread's score history + flags to disk.

    Writes ``<persistence_dir>/<thread_id>_scores.json``. Overwrites any
    existing file (latest wins). Per PRD §6.11.T1: pairs with the dashboard
    panel that lands in §6.8.T2 (Phase 2).

    Returns the path written to.
    """
    target = _scores_path(thread_id, persistence_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "thread_id": thread_id,
        "score_history": score_history,
        "score_trajectory_flags": score_trajectory_flags,
    }
    target.write_text(json.dumps(payload, indent=2))
    logger.debug("Score trajectory persisted: %s", target)
    return target


def load_score_trajectory(
    thread_id: str,
    *,
    persistence_dir: Path | None = None,
) -> tuple[list[dict[str, int]], list[str]]:
    """Load a thread's score history + flags from disk.

    Returns ``([], [])`` when the file is absent or malformed; the dashboard
    treats those identically to "no data yet" and the caller does not need
    to special-case missing files.
    """
    source = _scores_path(thread_id, persistence_dir)
    if not source.is_file():
        return [], []
    try:
        payload = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Corrupt score-trajectory file: %s — ignoring", source)
        return [], []
    if not isinstance(payload, dict):
        return [], []
    history = payload.get("score_history") or []
    flags = payload.get("score_trajectory_flags") or []
    if not isinstance(history, list) or not isinstance(flags, list):
        return [], []
    return history, flags


def parse_scores_from_review(review_text: str) -> dict[str, int]:
    """Extract dimension scores from a peer review output string.

    Looks for patterns like:

    - ``Argument Strength: 75/100``
    - ``argument_strength: 75``
    - ``| Argument Strength | 75 |``
    - ``| argument_strength | 75/100 |``

    Returns:
        Dict mapping dimension name (snake_case matching: :data:`DIMENSIONS`) to integer score, or empty dict if no
            scores found.
    """
    scores: dict[str, int] = {}
    for pattern in _SCORE_PATTERNS:
        for m in pattern.finditer(review_text):
            dim = _normalize_dimension(m.group("dim"))
            if dim is None:
                continue
            score = int(m.group("score"))
            if 0 <= score <= 100 and dim not in scores:
                scores[dim] = score
    return scores
