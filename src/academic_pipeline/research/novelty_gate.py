"""Compute novelty gate for a research topic (SCI Spec 3 Phase 1).

Pragmatic v1: use S2's /paper/search title-relevance ranking + difflib title
similarity to topic. Returns NoveltyGateResult with verdict in
{novel, partial, redundant}.

Phase 2 will add embedding-similarity scoring via S2's embedding endpoint
when their API stabilizes for free academic use.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from academic_pipeline.models.novelty_gate import NeighborPaper, NoveltyGateResult
from academic_pipeline.tools.bibliography.semantic_scholar import (
    _title_similarity,
    search_s2_by_title,
)


logger = logging.getLogger(__name__)


async def compute_novelty_gate(
    topic: str,
    tau_warn: float = 0.78,
    tau_block: float = 0.92,
    top_n: int = 10,
) -> NoveltyGateResult:
    """Search S2 for papers similar to the topic; compute title-difflib novelty verdict.

    Args:
        topic: The research topic (free-text string from intake).
        tau_warn: Below this max-similarity → NOVEL. Default 0.78.
        tau_block: At/above this → REDUNDANT (hard reject). Default 0.92.
        top_n: Cap on neighbors retained in the result. Default 10.

    Returns:
        NoveltyGateResult with verdict + neighbors. On S2 failure, returns
        NOVEL with a note explaining the degraded state (graceful fallback —
        infra issues must not block the pipeline).
    """
    try:
        raw = await search_s2_by_title(topic)
    except Exception as e:
        # Broad except by design: graceful degradation. Any S2 failure (network,
        # auth, parsing inside search_s2_by_title) must not block the pipeline.
        logger.warning("Novelty gate S2 search failed: %s; defaulting to NOVEL", e)
        return NoveltyGateResult(
            verdict="novel",
            max_similarity=0.0,
            nearest_neighbors=[],
            note=f"S2 unreachable; gate skipped: {e}",
        )

    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Novelty gate could not parse S2 response: %s; defaulting to NOVEL", e)
        return NoveltyGateResult(
            verdict="novel",
            max_similarity=0.0,
            nearest_neighbors=[],
            note=f"S2 response malformed; gate skipped: {e}",
        )

    if not isinstance(parsed, dict):
        return NoveltyGateResult(
            verdict="novel",
            max_similarity=0.0,
            nearest_neighbors=[],
            note="S2 returned unexpected payload shape; gate skipped",
        )

    if parsed.get("degraded"):
        err = parsed.get("error", "unknown")
        logger.warning("Novelty gate S2 returned degraded status: %s; defaulting to NOVEL", err)
        return NoveltyGateResult(
            verdict="novel",
            max_similarity=0.0,
            nearest_neighbors=[],
            note=f"S2 degraded: {err}",
        )

    # search_s2_by_title returns {"query": ..., "matches": [{paperId, title, doi, similarity, ...}]}
    matches = parsed.get("matches") or []
    candidates = matches[:top_n] if isinstance(matches, list) else []

    if not candidates:
        return NoveltyGateResult(
            verdict="novel",
            max_similarity=0.0,
            nearest_neighbors=[],
            note="No similar papers found in Semantic Scholar",
        )

    neighbors: list[NeighborPaper] = []
    max_sim = 0.0
    for c in candidates:
        if not isinstance(c, dict):
            continue
        title = str(c.get("title") or "")
        # Prefer the similarity already computed by search_s2_by_title; recompute
        # from the topic if missing or unparseable.
        sim_raw = c.get("similarity")
        try:
            sim = float(sim_raw) if sim_raw is not None else _title_similarity(topic, title)
        except (TypeError, ValueError):
            sim = _title_similarity(topic, title)
        sim = max(0.0, min(1.0, sim))
        if sim > max_sim:
            max_sim = sim
        doi_val = c.get("doi") or None
        s2_id_val = c.get("paperId")
        neighbors.append(
            NeighborPaper(
                title=title,
                doi=doi_val or None,
                semantic_scholar_id=str(s2_id_val) if s2_id_val else None,
                similarity=sim,
                abstract_excerpt=str(c.get("abstract") or "")[:200],
            )
        )

    neighbors.sort(key=lambda n: n.similarity, reverse=True)

    verdict: Literal["novel", "partial", "redundant"]
    if max_sim >= tau_block:
        verdict = "redundant"
        nearest_title = neighbors[0].title if neighbors else "(unknown)"
        note = (
            f"REDUNDANT: max title similarity {max_sim:.2f} >= block threshold {tau_block}. "
            f"Nearest: {nearest_title!r}"
        )
    elif max_sim >= tau_warn:
        verdict = "partial"
        note = (
            f"PARTIAL: max title similarity {max_sim:.2f} between warn {tau_warn} "
            f"and block {tau_block}. Differentiation needed (Phase 2 will inject paragraph)."
        )
    else:
        verdict = "novel"
        note = f"NOVEL: max title similarity {max_sim:.2f} < warn threshold {tau_warn}"

    return NoveltyGateResult(
        verdict=verdict,
        max_similarity=max_sim,
        nearest_neighbors=neighbors,
        note=note,
    )
