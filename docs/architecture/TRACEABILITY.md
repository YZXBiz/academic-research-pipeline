# Traceability Layer (SCI Port)

Ports data-to-paper's NEJM-AI-clearing trace mechanism into this pipeline. Every numerical claim in a generated manuscript carries a clickable hyperlink trace back to the code line that produced it. Peer reviewers can audit any number in 5 seconds.

**Spec:** `docs/superpowers/specs/2026-05-03-sci-traceability-port-design.md`
**Plan:** `docs/superpowers/plans/2026-05-03-sci-traceability-port-plan.md`
**Reference system:** [data-to-paper](https://github.com/Technion-Kishony-lab/data-to-paper) (Kishony lab, NEJM AI March 2025)

## Three seams

```
┌─────────────────────────────┐
│  Producer seam              │   experiment/graph.py::AnalysisNode
│  (experiment subgraph)      │   → experiment/producers.py::extract_numerical_products_from_result
│                             │   → state.numerical_store (PipelineState)
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Writer seam                │   writing/graph.py::ParallelSectionDraftNode
│  (section_writer agent)     │   → make_numeric_output_validator(store, ...)(section)
│                             │   → ModelRetry on bare numbers / hedges / unknown labels
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  Renderer seam              │   tools/rendering/latex_compiler.py::compile_pdf_pandoc
│  (LaTeX → PDF)              │   → apply_traceability_substitutions(text, store, mode, runs)
│                             │   → ⟨num:label⟩ → \hyperlink + Notes/Code appendices
└─────────────────────────────┘
```

## Modes (config.traceability_mode)

| Mode | What runs |
|---|---|
| `off` (default) | Layer is a no-op; existing pipeline behavior preserved verbatim |
| `partial` | Numerical store + writer validator + Notes appendix |
| `full` | Adds writer↔reviewer dialogue + curated context + Code appendix with line hypertargets |

## Trace chain (worked example)

A paper claims "Our model achieved AUC 0.87 on the held-out set."

1. **Producer**: `AnalysisNode` runs `analysis.py:42` (`auc = roc_auc_score(...)`); experiment/producers.py registers `NumericalProduct(label="auc", value="0.87", source_code_line="analysis.py:42", ...)` → `state.numerical_store`.
2. **Writer**: section_writer emits `Our model achieved AUC ⟨num:auc⟩ on the held-out set.` Validator confirms `auc` exists in store, no bare numbers in prose, no hedge phrases.
3. **Renderer**: `apply_traceability_substitutions` replaces with `\hyperlink{num_auc}{0.87}` and appends Notes appendix:
   ```latex
   \section{Calculation Notes}
   \begin{itemize}
   \item \hypertarget{num_auc}{}\textbf{0.87} — Test-set AUC. Computed as: roc_auc_score(y, p). See \hyperlink{code_run-x_42}{analysis.py:42}.
   \end{itemize}
   ```
4. **Code appendix** (full mode): emits `\hypertarget{code_run-x_42}{}` at the producing line in the included code listing.
5. **PDF**: pandoc + tectonic compile via `hyperref`. Reviewer clicks "0.87" → jumps to Notes entry → clicks "analysis.py:42" → jumps to source line. **5 seconds, no contact required.**

## Module layout

```
src/academic_pipeline/
├── traceability/                      # this layer
│   ├── _patterns.py                   # NUM_TOKEN_PATTERN single source of truth
│   ├── errors.py                      # TRC001-TRC006 typed exceptions
│   ├── validators.py                  # output validator factory + ported d2p regex
│   ├── substitution.py                # ⟨num:label⟩ → \hyperlink renderer
│   ├── notes_appendix.py              # Notes appendix with code backlinks
│   ├── code_appendix.py               # Code appendix with line hypertargets
│   ├── context_spec.py                # ContextSpec model
│   ├── dialogue.py                    # writer↔reviewer N-turn dialogue
│   └── copilot.py                     # checkpoint stdin handler
├── models/numerical.py                # NumericalProduct + NumericalStore
└── experiment/producers.py            # producer-side helper (lives in experiment/, not traceability/)
```

## What's not yet implemented (v1 gaps)

- ~~Code appendix empty in full mode~~ — **Closed 2026-05-04** by `experiment/line_tracer.py` (AST analysis of executed script). Code appendix now emits `\hypertarget` markers at lines that wrote to the results dict. Dynamic keys (f-string labels, loop assignments) still degrade gracefully to no anchor.
- **SectionDialogueNode helper exists but isn't wired** — `traceability/dialogue.py::run_writer_reviewer_dialogue` is available for use but the writing graph still uses `ParallelSectionDraftNode`. Wiring the dialogue node is a future task.
- **Per-agent ContextSpec yaml files don't exist** — `build_curated_context()` is available but no agent currently declares its spec. Wiring per-agent specs is a separate rollout.
- **Copilot 3-bullet summarizer agent removed** — Task 19 of the original plan was dropped (would have shipped dead code). The copilot helper takes a summary string from the calling node directly.

## How a number-fabricating regression is caught

Suppose the section_writer produces `"Pooled OR was 1.42 (95% CI 1.18-1.71)"` from thin synthesis (no actual analysis ran). When `traceability_mode != "off"`:

1. Validator scans output → finds bare `1.42` not in any `⟨num:...⟩` wrapper
2. Validator raises `ModelRetry("The number '1.42' appears in prose without a ⟨num:...⟩ wrapper. ...")`
3. PydanticAI auto-retries; if retries exhaust, the existing eval-panel revision flow takes over
4. The fabricated number never reaches the PDF

This regression class is documented in `tests/unit/traceability/test_validator_regressions.py` — every historical fabrication that fooled the eval panel is now a test fixture. Add a new fixture per future fabrication caught in production.

---

# Reference (per-mechanism)

The five surfaces the rest of the codebase depends on, enumerated in one
place per PRD §6.10.T7. The architecture overview (above) explains the
three seams; this section drills into the contract of each mechanism.

## Token shape

A traceability token in section text is `⟨num:label⟩` where:

- The opening bracket is **U+27E8** (`MATHEMATICAL LEFT ANGLE BRACKET`).
- The closing bracket is **U+27E9** (`MATHEMATICAL RIGHT ANGLE BRACKET`).
- `label` is `[A-Za-z_][A-Za-z0-9_]*` (Python identifier syntax).

**Do NOT** use ASCII `<>` or `{{ }}`. The single source of truth is
`traceability/_patterns.py::NUM_TOKEN_PATTERN`. Both the validator and the
substitution renderer import it; there is no second copy anywhere.

```python
import re
from academic_pipeline.traceability._patterns import NUM_TOKEN_PATTERN

re.findall(NUM_TOKEN_PATTERN, "AUC ⟨num:auc⟩ on ⟨num:test_n⟩ samples")
# → ['auc', 'test_n']
```

**Resolution** happens at render time via
`traceability/substitution.py::substitute_tokens(text, store, output_format)`:

| Output format | Replacement |
|---|---|
| `"latex"` | `\hyperlink{num_<label>}{<value>}` |
| `"html"` | bare `<value>` |

The matching `\hypertarget{num_<label>}` lives in the Notes appendix.

## Validator gate

Attached to `section_writer` agents at runtime via the
`make_numeric_output_validator(store, ...)` factory at
`traceability/validators.py`. The returned function plugs into PydanticAI's
`agent.run(output_validators=[...])` slot. Four checks run in order:

1. **Aborting phrases** (`UnexpectedModelBehavior`, no retry). 9 phrases
   per `validators.py:42-45`. The `[PENDING:...]` carve-out is preserved
   per PRD AP56.
2. **Unknown `⟨num:label⟩` tokens** (`ModelRetry`). The label must be a
   key in `store.products`. Error message lists up to 10 known labels.
3. **Bare numbers in prose** (`ModelRetry`). Numeric pattern (ported
   verbatim from data-to-paper) catches `42`, `0.87`, `1,234.56`,
   `1.23e-4`, etc. Tokens are stripped first.
4. **Hedge phrases near tokens** (`ModelRetry`). 5 phrases per
   `validators.py:37-39` — only when within `HEDGE_PROXIMITY_TOKENS`
   (default 5) word tokens **before** a `⟨num:...⟩`. Hedge AFTER the
   number is allowed (it summarises, not weasels).

**Score immutability** (PRD AP57): when a hard veto fires, the caller
MUST NOT mutate `EvaluationResult.scores`.

**Editorial-gate hard-fail** (PRD §6.10.T4):
`writing/graph.py::FormatterNode` calls
`traceability/substitution.py::find_unresolved_tokens(text, store)`
against the merged paper_draft text BEFORE the formatter runs. If any
tokens lack matching products, raises `SubstitutionFailure` (TRC003)
with the full unresolved list — surfaces problems at editorial time
instead of LaTeX compile time.

## Dialogue helper

`traceability/dialogue.py::run_writer_reviewer_dialogue(...)` runs an
N-turn writer↔reviewer exchange that terminates on a fixed phrase.
Helper exists; **wiring into `writing/graph.py` is deferred to PRD
§6.10.T1 in Phase 4** (pairs with §6.3.T9 + §6.9.T3).

Termination phrase: **`"The section does not require any changes"`** —
verbatim, including capitalisation. Do NOT change the phrase without
updating every consumer (per PRD ralph-54).

`max_turns` default 5. On exhaustion the helper raises
`DialogueExhaustion` (TRC006).

## Appendices (auto-attach contract)

### Notes appendix (`traceability/notes_appendix.py`)

Auto-attached by
`tools/rendering/latex_compiler.py::apply_traceability_substitutions`
when **any** token is cited and `traceability_mode != "off"` (PRD
§6.10.T5).

- Emits `\section{Calculation Notes}` with one `\item` per cited label.
- Each item carries `\hypertarget{num_<label>}` (the click target),
  the value + unit, the formula, and a `\hyperlink{code_<run>_<line>}`
  backlink to the Code appendix source line.
- **Empty cited set → empty string** (caller skips the section). This
  prevents `\begin{itemize}\end{itemize}` which crashes tectonic.

### Code appendix (`traceability/code_appendix.py`)

Auto-attached only in **full** mode AND when at least one
experiment_run has source code. Emits `\section{Code: <filename>}`
with `\hypertarget` markers at the lines that wrote to the results
dict (per `experiment/line_tracer.py` AST analysis, shipped 2026-05-04).

Dynamic keys (f-string labels, loop assignments) degrade gracefully to
no anchor — the listing still appears, just without per-line jumps.

## Error codes (TRC namespace)

Six typed exceptions at `traceability/errors.py`, all inheriting
`TraceabilityError`:

| Code | Class | When raised | Severity |
|---|---|---|---|
| TRC001 | `NumericValidatorRetry` | Hedge / unknown label / bare number | `ModelRetry` (auto-retry) |
| TRC002 | `NumericValidatorAbort` | Aborting phrase detected | `UnexpectedModelBehavior` (no retry) |
| TRC003 | `SubstitutionFailure` | Unresolved `⟨num:label⟩` at render | Pipeline error (gate hard-fail) |
| TRC004 | `StoreIntegrityError` | Duplicate label or missing source_code_line | Producer-side bug |
| TRC005 | `CopilotTimeout` | HITL stdin timeout | Continues autonomous |
| TRC006 | `DialogueExhaustion` | `max_turns` hit without termination | Section escalates to revision |

### Emitting to events.jsonl (PRD §6.10.T6)

```python
from academic_pipeline.traceability.errors import (
    SubstitutionFailure,
    traceability_error_event,
)

err = SubstitutionFailure("unresolved", label="auc", store_label_count=12)
event_logger.emit_sync("traceability_error", **traceability_error_event(err))
```

Payload shape: `{error_code, message, **public_context_fields}`. `ts`
and `type` are stamped by `EventLogger`. The helper uses `vars()` on
the exception instance, so per-error context fields auto-flow without
per-class boilerplate.

## See also

- [TRACEABILITY_RUNBOOK.md](./TRACEABILITY_RUNBOOK.md) — symptom →
  file map + postmortem grep recipes.
- `src/academic_pipeline/traceability/README.md` — module-by-module
  responsibilities + wired call sites.
