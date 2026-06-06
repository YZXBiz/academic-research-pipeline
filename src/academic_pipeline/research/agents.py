"""Research agent registry.

Centralises all Agent.from_file() definitions and tool wiring for the
research subgraph.  Imported by ``graph.py`` as
``from academic_pipeline.research.agents import agents as _agents``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicCompaction
from pydantic_ai_skills import SkillsCapability

from academic_pipeline.config import DEFAULT_CONFIG, SKILLS_DIRS
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.models.chain import DevelopmentChain, ThesisStatement
from academic_pipeline.models.research import (
    Bibliography,
    IndependentVerificationReport,
    MethodologyBlueprint,
    ResearchReport,
    RQBrief,
    SourceVerificationReport,
    SynthesisReport,
)
from academic_pipeline.models.review import EditorReview
from academic_pipeline.research.synthesis_validator import validate_synthesis_report
from academic_pipeline.runtime.model_registry import build_agent
from academic_pipeline.runtime.throttle import throttle_hooks
from academic_pipeline.tools.bibliography.doi import (
    check_retraction,
    resolve_doi_metadata,
    verify_doi,
)
from academic_pipeline.tools.bibliography.exa import web_fetch_exa, web_search_exa
from academic_pipeline.tools.bibliography.semantic_scholar import (
    batch_verify_s2,
    get_s2_paper_details,
    search_s2_by_title,
)


_COMPACTION = AnthropicCompaction(token_threshold=DEFAULT_CONFIG.compaction_token_threshold)


_AGENTS_DIR = Path(__file__).parent / "specs"

agents: dict[str, Agent[PipelineDeps, Any]] = {
    "research_question": build_agent(
        "research_question",
        _AGENTS_DIR / "research_question.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(RQBrief),
        capabilities=[throttle_hooks],
    ),
    "research_architect": build_agent(
        "research_architect",
        _AGENTS_DIR / "research_architect.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(MethodologyBlueprint),
        capabilities=[throttle_hooks],
    ),
    "bibliography": build_agent(
        "bibliography",
        _AGENTS_DIR / "bibliography.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(Bibliography),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), _COMPACTION],  # pyright: ignore[reportArgumentType]
        tools=[web_search_exa, web_fetch_exa],
    ),
    "source_verification": build_agent(
        "source_verification",
        _AGENTS_DIR / "source_verification.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(SourceVerificationReport),
        capabilities=[throttle_hooks],
        tools=[
            verify_doi,
            check_retraction,
            resolve_doi_metadata,
            search_s2_by_title,
            batch_verify_s2,
            get_s2_paper_details,
        ],
    ),
    # PRD §6.1.T7 — knowledge_graph agent + spec deleted (legacy KG retired).
    "chain_of_ideas_extractor": build_agent(
        "chain_of_ideas_extractor",
        _AGENTS_DIR / "chain_of_ideas_extractor.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(DevelopmentChain),
        capabilities=[throttle_hooks],
    ),
    "thesis_extractor": build_agent(
        "thesis_extractor",
        _AGENTS_DIR / "thesis_extractor.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ThesisStatement),
        capabilities=[throttle_hooks],
    ),
    "synthesis": build_agent(
        "synthesis",
        _AGENTS_DIR / "synthesis.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(SynthesisReport),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "report_compiler": build_agent(
        "report_compiler",
        _AGENTS_DIR / "report_compiler.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ResearchReport),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
    "independent_verifier": build_agent(
        "independent_verifier",
        _AGENTS_DIR / "independent_verifier.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(IndependentVerificationReport),
        capabilities=[throttle_hooks],
    ),
    "editor_in_chief": build_agent(
        "editor_in_chief",
        _AGENTS_DIR / "editor_in_chief.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(EditorReview),
        capabilities=[throttle_hooks, _COMPACTION],  # pyright: ignore[reportArgumentType]
    ),
}

# PRD §6.1.T3 — synthesis output validator enforces non-empty themes / gaps /
# debates / methodology recommendations. Defense in depth on top of Pydantic.
agents["synthesis"].output_validator(validate_synthesis_report)
# PRD §6.1.T6 — `ethics_review` agent + spec moved to integrity (see
# `academic_pipeline.integrity.agents`).
