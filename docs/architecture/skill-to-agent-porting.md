# Skill → Agent Porting Contract

How an upstream `academic-research-skills` skill becomes an agent in this
PydanticAI pipeline. Follow this for every port so the architecture stays
consistent.

## What maps to what

| Upstream (Claude-Code skill) | Here (PydanticAI) |
|---|---|
| `SKILL.md` (orchestrator) | a subgraph in `<sub>/graph.py` + node wiring |
| `agents/<x>_agent.md` (a persona + prompt) | `<sub>/specs/<x>.yaml` + an output model + a node + a registry entry |
| `references/*.md` (protocols, tools) | functions in `tools/` (wired into the agent's `tools=`) |
| `model: inherit` | nothing — `build_agent` injects `config.default_model` |
| "Phase Boundary: you MUST NOT write outside phase N" | nothing — enforced by graph topology; a node returns typed state, it cannot act out of phase |

Key inversion: upstream agents are free markdown personas they *police* with
prompts + hooks (scoped-write guard, passport markers). Here, agents are typed
graph nodes — they return a `PromptedOutput(Model)` and the graph decides what
runs next, so the whole class of "agent wandered out of its phase" is impossible
by construction. Do **not** port their guard/marker machinery; it solves a
problem this architecture doesn't have.

## Porting one agent — the 5 touchpoints

1. **Output model** — define a frozen Pydantic model for the deliverable in
   `models/`. This is the contract; upstream relies on the LLM emitting the right
   markdown, we enforce a schema.
2. **Spec** — `<sub>/specs/<x>.yaml`: translate the agent.md body into
   `instructions`. **No `model:` line** (build_agent injects it). Put provider-
   neutral settings (`max_tokens`) under `model_settings`; reasoning effort is
   handled by `MAX_REASONING_AGENTS` in `runtime/model_registry.py`, not the spec.
3. **Registry** — add a `build_agent("<x>", _AGENTS_DIR / "<x>.yaml", deps_type=
   PipelineDeps, output_type=PromptedOutput(<Model>), capabilities=[...], tools=[...])`
   entry to `<sub>/agents.py`. Always `build_agent`, never `Agent.from_file`.
4. **Node** — a `@dataclass` `BaseNode[<State>, PipelineDeps, str]` in
   `<sub>/graph.py` that runs the agent via `run_with_evaluation()` (quality-gated)
   or `traced_agent_run()` (utility), writes the result to state, returns the next
   node. Never `agent.run()` directly.
5. **Graph** — add the node to `build_<sub>_graph()` and wire the edge from the
   preceding node's `run()` return.

## Rules (non-negotiable)

- **Typed output, always.** `PromptedOutput(Model)`; add an `output_validator`
  for invariants Pydantic can't express.
- **`build_agent`, not `Agent.from_file`.** Model selection is centralized.
- **A skill that is a multi-step workflow ports to a subgraph, not one agent.**
  Map each phase to a node; do not cram a workflow into a single agent.
- **Trust boundary on external content.** Anything fetched from outside (Exa
  `web_search_exa`/`web_fetch_exa`, future web tools) is untrusted and MUST be
  wrapped via `_wrap_untrusted` before it reaches an agent — the tool layer is
  the chokepoint, not each agent prompt. Never hand an agent raw external text.
- **Code standards** (`.claude/CLAUDE.md`): `from __future__ import annotations`,
  frozen models, typed collections, terse docstrings, no banner/essay comments.

## Example (synthesis)

Upstream `agents/synthesis_agent.md` (persona + "Phase 3 only" boundary) →
- `models/research.py::SynthesisReport`
- `research/specs/synthesis.yaml` (the prompt; no model line)
- `research/agents.py`: `build_agent("synthesis", ..., output_type=PromptedOutput(SynthesisReport))`
  + `agents["synthesis"].output_validator(validate_synthesis_report)`
- `research/graph.py::SynthesisNode` → returns `ReportCompilerNode`

The "Phase 3 only" rule needs no port: `SynthesisNode` returns `ReportCompilerNode`
and writes only `state.synthesis` — it structurally cannot do phase-4 work.

## When NOT to port
Skip anything that is Claude-Code-skill runtime: PreToolUse hooks, scoped-write
guards, passport/terminal markers, `/ars-*` commands, plugin manifests,
MODE_REGISTRY, Cowork packaging, multi-language docs. These have no analog (and no
need) in an autonomous typed-graph pipeline.
