"""Per-agent ContextSpec instances for experiment-subgraph agents.

Mirrors writing/context_specs.py + review/context_specs.py per PRD §6.10.T3.
The ContextSpec class lives at `traceability/context_spec.py`; only
INSTANCES are per-agent.

PRD AP75: `build_curated_context` performs strict
`isinstance(spec, ContextSpec)` — never pass a dict in place.
"""

from __future__ import annotations

from academic_pipeline.traceability.context_spec import ContextSpec


# `result_analyzer` reads topic, rq_brief, synthesis, and results to
# produce a peer-reviewable analysis. Needs full numerical_store access
# because the analysis cites raw experiment numbers via ⟨num:label⟩.
RESULT_ANALYZER_CONTEXT_SPEC = ContextSpec(
    allowed_products=[
        "topic",
        "rq_brief",
        "synthesis",
        "results",
    ],
    allowed_numerical_labels="all",
)
