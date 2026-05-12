# traceability/

SCI traceability layer. See:
- `docs/architecture/TRACEABILITY.md` — architecture + trace chain
- `docs/architecture/TRACEABILITY_RUNBOOK.md` — symptom → file map + postmortem grep
- `docs/superpowers/specs/2026-05-03-sci-traceability-port-design.md` — design rationale

## Files

- `_patterns.py` — `NUM_TOKEN_PATTERN` single source of truth (imported by validators + substitution)
- `errors.py` — typed exceptions TRC001-TRC006
- `validators.py` — output validator factory + ported data-to-paper regex; called inline from `writing/graph.py::ParallelSectionDraftNode`
- `substitution.py` — `⟨num:label⟩` → `\hyperlink{num_<label>}{value}` renderer
- `notes_appendix.py` — Calculation Notes LaTeX section with code-line backlinks
- `code_appendix.py` — Code appendix with `\hypertarget` at producing lines
- `context_spec.py` — `ContextSpec` model
- `dialogue.py` — writer↔reviewer N-turn dialogue (helper; not yet wired into writing graph)
- `copilot.py` — checkpoint stdin handler

**Producer logic lives elsewhere by design**: `experiment/producers.py::extract_numerical_products_from_result` extracts `NumericalProduct`s from experiment results. Kept in `experiment/` because the logic is experiment-specific. `traceability/` only owns receiver-side logic.

## Wired call sites

| File | Where | What it does |
|---|---|---|
| `pipeline/nodes.py` (ExperimentPhaseNode) | success branch | calls `extract_numerical_products_from_result`, populates `state.numerical_store` |
| `pipeline/nodes.py` (IntakeNode / ExperimentPhaseNode / WritePhaseNode) | end of run() | optional `copilot_checkpoint` (--copilot flag) |
| `pipeline/nodes.py` (WritePhaseNode) | WritingState construction | forwards `numerical_store` from PipelineState → WritingState |
| `writing/graph.py` (ParallelSectionDraftNode) | after `run_with_evaluation` | inline numeric output validator |
| `writing/graph.py` (LatexCompilerNode) | when calling `compile_pdf_pandoc` | passes `numerical_store`, `traceability_mode`, `experiment_runs` |
| `tools/rendering/latex_compiler.py` (compile_pdf_pandoc) | before pandoc invocation | `apply_traceability_substitutions(text, store, mode, runs)` |

## Off-mode contract

When `config.traceability_mode == "off"`:
- Validator is NOT invoked (call-site guard)
- `apply_traceability_substitutions` is a pure passthrough
- Producer never registers products
- Copilot checkpoints return None immediately

The whole layer is a structured no-op. Existing pipeline behavior is preserved bit-for-bit.
