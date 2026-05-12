"""Chain-of-Ideas models for narrative-spine literature representation.

Provides the data structures for the SCI-traceability "Chain of Ideas" port
(Spec 2 Phase 1, see ``docs/superpowers/specs/2026-05-03-chain-of-ideas-kg-design.md``).

A ``DevelopmentChain`` is a 5-15 milestone narrative arc showing how a field
arrived at the current state and ending at an unsolved problem. A
``ThesisStatement`` is a falsifiable claim grounded in the chain's terminal
unsolved problem.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class MilestoneType(StrEnum):
    """Categorisation of a development-chain milestone."""

    CONCEPT_INTRO = "concept_intro"
    METHOD_EXT = "method_ext"
    BENCHMARK = "benchmark"
    REFUTATION = "refutation"
    APPLICATION = "application"


class EdgeRelation(StrEnum):
    """How one milestone relates to another along the chain."""

    EXTENDS = "extends"
    REFUTES = "refutes"
    SUPERSEDES = "supersedes"
    APPLIES_TO = "applies_to"


class Milestone(BaseModel):
    """A single research milestone in a DevelopmentChain."""

    model_config = ConfigDict(frozen=True)

    milestone_id: str
    milestone_type: MilestoneType
    year: int
    key_paper_doi: str | None
    key_paper_title: str
    one_sentence_advance: str


class ChainEdge(BaseModel):
    """A relation between two milestones in a DevelopmentChain."""

    model_config = ConfigDict(frozen=True)

    from_milestone: str
    to_milestone: str
    relation: EdgeRelation


class DevelopmentChain(BaseModel):
    """A 5-15 milestone narrative arc ending at an unsolved problem."""

    model_config = ConfigDict(frozen=True)

    milestones: list[Milestone]
    edges: list[ChainEdge]
    terminal_unsolved_problem: str


class ThesisStatement(BaseModel):
    """A falsifiable thesis grounded in a DevelopmentChain milestone."""

    model_config = ConfigDict(frozen=True)

    claim: str
    novelty_dimension: Literal[
        "new_concept", "method_extension", "new_application", "refutation"
    ]
    grounded_in_milestone: str
