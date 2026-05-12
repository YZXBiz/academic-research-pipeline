"""Models for the Semantic Scholar novelty gate (SCI Spec 3 Phase 1).

The novelty gate runs after IntakeNode and before ResearchPhaseNode. It
queries Semantic Scholar for papers similar to the topic, computes
title-difflib similarity, and produces a verdict in {novel, partial, redundant}.

Phase 1 is hard-reject only: REDUNDANT verdicts return End from the node;
PARTIAL/NOVEL pass through. Phase 2 will add a differentiation paragraph
for PARTIAL verdicts (separate spec).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NeighborPaper(BaseModel):
    """A single Semantic Scholar candidate paper near the topic in title-space."""

    model_config = ConfigDict(frozen=True)

    title: str
    doi: str | None = None
    semantic_scholar_id: str | None = None
    similarity: float = Field(ge=0.0, le=1.0)
    """Title-difflib similarity to the queried topic in [0, 1]."""
    abstract_excerpt: str = ""
    """First 200 chars of abstract or empty string."""


class NoveltyGateResult(BaseModel):
    """Result of the novelty gate computation."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["novel", "partial", "redundant"]
    max_similarity: float = Field(ge=0.0, le=1.0)
    nearest_neighbors: list[NeighborPaper] = Field(default_factory=list)
    """Top-N neighbors sorted by similarity descending."""
    note: str
    """Human-readable explanation of the verdict (also shown to operator on REDUNDANT)."""
