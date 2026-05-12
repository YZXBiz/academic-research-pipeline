"""Per-agent ContextSpec instances for writing-subgraph agents.

The ContextSpec class lives at `traceability/context_spec.py` — only
INSTANCES are per-agent (PRD §6.10.T2 + ralph-57). Adding a new agent
to the curated-context regime means appending a new spec instance here
and replacing its node's `build_context(...)` call with
`build_curated_context(state, AGENT_SPEC)`.

PRD AP75: `build_curated_context` performs a strict
`isinstance(spec, ContextSpec)` check — never pass a dict in place of
one of these instances.
"""

from __future__ import annotations

from academic_pipeline.traceability.context_spec import ContextSpec


# `draft_writer` consumes the same 8 state fields the legacy
# `build_context(...)` call in `DraftWriterNode` listed. It needs full
# numerical-store access to cite any value via `⟨num:label⟩` tokens, so
# `allowed_numerical_labels="all"` (the Literal sentinel for full store
# access — distinct from `[]` which would deny all numerical citations).
DRAFT_WRITER_CONTEXT_SPEC = ContextSpec(
    allowed_products=[
        "topic",
        "paper_outline",
        "argument_blueprint",
        "bibliography",
        "internal_review",
        "experiment_results",
        "experiment_analysis",
        "experiment_figures",
    ],
    allowed_numerical_labels="all",
)


# `section_writer` consumes the experiment artifacts plus topic. The
# SectionSpec itself is a per-call argument constructed by the parent
# planner — not from PipelineState — so it isn't listed here.
SECTION_WRITER_CONTEXT_SPEC = ContextSpec(
    allowed_products=[
        "topic",
        "experiment_results",
        "experiment_analysis",
        "experiment_figures",
    ],
    allowed_numerical_labels="all",
)
