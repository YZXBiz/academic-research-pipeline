# Traceability Runbook

When the traceability layer breaks, look here.

## Symptom → Where to look

| Symptom | First check | Then |
|---|---|---|
| Writer keeps retrying the same section | `events.jsonl` filter `error_code=TRC001` | Inspect the section's `available_labels` in the retry message — likely the producer didn't register the label the writer needs |
| PDF compile fails on `\hyperlink` | `traceability/substitution.py` raised `SubstitutionFailure` (`error_code=TRC003`) | A `⟨num:label⟩` token in writer output doesn't match any store entry. Bug in validator (it should have caught this) — file an issue + add a regression fixture |
| `StoreIntegrityError` (`TRC004`) — duplicate label | `experiment/producers.py` is double-registering | Check whether AnalysisNode runs twice for the same run; usually a re-run with the same `run_id` |
| Section finalizes with `[GAP]` placeholders | `events.jsonl` filter `error_code=TRC002` | Aborting phrase (`[insert`, `subject to revision`, etc.) detected. Trace upstream synthesis quality — writer was producing placeholders because it didn't have grounded content |
| `--copilot` flag set but no prompt appears | `config.copilot_enabled` is `True`? | Check whether the pipeline reached the checkpoint (post_intake / post_experiment_design / post_first_draft). If yes, `traceability/copilot.py` stdin handling — likely TimeoutError silently caught |
| Dialogue runs forever | `config.max_dialogue_turns` (default 3) | Reviewer agent never emits the termination phrase. Check `events.jsonl` for `DialogueExhaustion` (`TRC006`) warning |
| Trace appendix empty in PDF | `config.traceability_mode == "off"` (default) | Set to `"partial"` or `"full"` in `configs/dev.yaml` or via env: `TRACEABILITY_MODE=full` |
| Code appendix empty even with `traceability_mode=full` | This is **expected v1 behavior** | `producing_lines` data isn't tracked in the pipeline yet. Notes appendix + inline hyperlinks still work fully |
| `apply_traceability_substitutions` not called | `latex_compiler.py::compile_pdf_pandoc` is being called without `numerical_store` kwarg | `LatexCompilerNode` should pass it from `WritingState`. Verify wire-up at `writing/graph.py::LatexCompilerNode.run` |
| `WritingState.numerical_store` is empty when validator runs | `WritePhaseNode` (`pipeline/nodes.py:237`) isn't forwarding the store | Should pass `numerical_store=ctx.state.numerical_store` when constructing `WritingState`. Check the construction call |

## Postmortem grep templates

Every traceability error logs a structured event. Single-grep recipes:

```bash
# All traceability errors across all runs
jq 'select(.type=="traceability_error")' output/*/events.jsonl

# Just the validator-retry rejections (most common — writer hallucinated)
jq 'select(.type=="traceability_error" and .error_code=="TRC001")' output/*/events.jsonl

# Just the unrecoverable aborts (writer was confused / synthesis was thin)
jq 'select(.type=="traceability_error" and .error_code=="TRC002")' output/*/events.jsonl

# Substitution failures (renderer bugs)
jq 'select(.type=="traceability_error" and .error_code=="TRC003")' output/*/events.jsonl

# How many of each error type per run
jq -s 'group_by(.error_code) | map({code: .[0].error_code, count: length})' \
   output/<run-id>/events.jsonl
```

## Error code legend

| Code | Class | Severity | Auto-recovery |
|---|---|---|---|
| TRC001 | `NumericValidatorRetry` | Recoverable | PydanticAI auto-retries up to 3 |
| TRC002 | `NumericValidatorAbort` | Section-fatal | None — section gets `[GAP]` |
| TRC003 | `SubstitutionFailure` | Run-fatal | None — bug, file issue |
| TRC004 | `StoreIntegrityError` | Run-fatal | None — bug in producer |
| TRC005 | `CopilotTimeout` | Informational | Continues autonomously |
| TRC006 | `DialogueExhaustion` | Section-degraded | Last writer output kept with warning |

## Fixture management for the PDF audit

Once you've generated a real `traceability_mode=full` run that you trust:

```bash
# Copy the output PDF to the test fixtures directory
cp output/<good-run-id>/paper.pdf tests/medium/traceability/fixtures/full_mode_sample.pdf

# Then the audit test runs every time you call:
make test-traceability-medium
```

The fixtures directory is gitignored (large binaries). If the fixture goes stale (e.g., the renderer changed), regenerate.

## Adding a new regression case

Every time you catch a fabrication or trace bug in production, add a fixture to the regression suite so it can never come back:

1. Open `tests/unit/traceability/test_validator_regressions.py`
2. Add a new entry to `REGRESSIONS`:
   ```python
   HistoricalFabrication(
       name="brief_kebab_case_description",
       section_text="The exact prose that fooled the validator",
       available_labels=("labels", "in", "store", "at", "the", "time"),
       expected_exception=ModelRetry,  # or UnexpectedModelBehavior
   ),
   ```
3. Run: `uv run pytest tests/unit/traceability/test_validator_regressions.py -v`
4. If the new fixture fails: fix the validator. If it passes: ship the fix + the new test together.
