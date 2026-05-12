"""Per-agent ContextSpec instances for review-subgraph agents.

Mirrors writing/context_specs.py per PRD §6.10.T3. The ContextSpec class
lives at `traceability/context_spec.py`; only INSTANCES are per-agent.

PRD AP75: `build_curated_context` performs strict
`isinstance(spec, ContextSpec)` — never pass a dict in place of one of
these instances.
"""

from __future__ import annotations

from academic_pipeline.traceability.context_spec import ContextSpec


# `editorial_synthesizer` reads paper_draft + reviewer_reports, plus
# cascade_result when cascaded_review_enabled. It does not cite numerical
# values — its job is decide/justify, not present numbers — so
# `allowed_numerical_labels=[]` (distinct from "all").
EDITORIAL_SYNTHESIZER_CONTEXT_SPEC = ContextSpec(
    allowed_products=[
        "paper_draft",
        "reviewer_reports",
        "cascade_result",
    ],
    allowed_numerical_labels=[],
)


# Persona-anchored reviewers (Spec 5 Phase 1). Each reads only paper_draft
# per the actual call site (review/graph.py:_run_persona_reviewer). Three
# distinct instances per PRD §6.10.T3 ("3 personas — 3 instances") so each
# persona keeps its own context isolation guarantee.
SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC = ContextSpec(
    allowed_products=["paper_draft"],
    allowed_numerical_labels=[],
)

APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC = ContextSpec(
    allowed_products=["paper_draft"],
    allowed_numerical_labels=[],
)

METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC = ContextSpec(
    allowed_products=["paper_draft"],
    allowed_numerical_labels=[],
)


# Lookup table mapping persona agent_key (per PERSONA_REVIEWER_AGENTS in
# review/agents.py) to its ContextSpec. Used by ParallelReviewerNode to
# pick the right spec when dispatching a persona run.
PERSONA_REVIEWER_SPECS: dict[str, ContextSpec] = {
    "senior_gatekeeper_reviewer": SENIOR_GATEKEEPER_REVIEWER_CONTEXT_SPEC,
    "applied_practitioner_reviewer": APPLIED_PRACTITIONER_REVIEWER_CONTEXT_SPEC,
    "methodology_purist_reviewer": METHODOLOGY_PURIST_REVIEWER_CONTEXT_SPEC,
}
