# Observability

How traces flow from the pipeline into Logfire and what to do when they
don't. Project: **research-demo** (per OQ18) at
[logfire-us.pydantic.dev/yzxbiz/research-demo](https://logfire-us.pydantic.dev/yzxbiz/research-demo).

This file covers the span schema, degradation modes, debug runbook,
and how to swap the Logfire project. For the architecture overview of
events.jsonl (the on-disk source of truth), see PRD §18.

---

## Span schema

Two complementary records per pipeline event:

1. **events.jsonl line** — `{"ts": float, "type": str, **fields}` written
   to `output/<run-id>/events.jsonl` by `EventLogger.emit_sync` (PRD §6.8).
2. **Logfire span** — emitted via `logfire.span(f"event:{type}", **fields)`
   alongside the jsonl line for the **5 new event types** (PRD §6.13.T1):
   - `recovery_event`
   - `doi_gate_failure`
   - `cascade_verdict`
   - `novelty_gate_verdict`
   - `ethics_checklist_result`

Per PRD AP37, the span and jsonl record share the same `error_code` and
`ts` (within ±1s — both happen in `EventLogger.emit_sync`), so you can
correlate Logfire searches against the on-disk event log.

Legacy event types (`pipeline_start`, `stage_change`, `node_complete`,
`node_error`, `pipeline_complete`, `pipeline_error`, `watchdog_*`) only
land in events.jsonl; their parallel observability is the global httpx
instrumentation + per-agent PydanticAI spans.

### Per-agent tags

Each PydanticAI agent invocation through `runtime/trace_logger.py::traced_agent_run`
gets `logfire.instrument_pydantic_ai(agent)` called once (PRD §6.13.T3).
The resulting spans carry the agent's `name` attribute as a Logfire tag.
Filter Logfire queries with `agent_name = "section_writer"` etc.
Idempotency guard: each agent is instrumented at most once per process
(set keyed by `id(agent)`).

### Tracing health line

`configure_observability()` emits one info-level startup line per PRD §6.13.T2:

```
tracing health: status=enabled project=research-demo dashboard=https://logfire-us.pydantic.dev/yzxbiz/research-demo
```

`status` is `enabled` when `LOGFIRE_TOKEN` is set, otherwise `token-absent`.
The line lands in stdout/stderr regardless of whether traces actually
upload — useful for confirming wiring at a glance.

---

## Degradation modes

| Symptom | Cause | Behavior | Fix |
|---|---|---|---|
| Tracing health line says `token-absent` | No `LOGFIRE_TOKEN` env var | Pipeline runs normally; spans are no-ops | `export LOGFIRE_TOKEN=...` then re-run |
| Tracing health line absent | Pipeline crashed before `configure_observability` | No traces this run | Inspect `output/<run-id>/events.jsonl` for the actual failure |
| Health line says `enabled` but no spans in Logfire UI | Logfire backend unreachable (network / token revoked / quota exhausted) | `logfire.span` calls silently no-op; pipeline continues | Check Logfire status page; re-issue token; raise project quota |
| Some spans missing, others present | One specific event type's emission failed | Each `_emit_event_span` call is wrapped in try/except — failures silenced | Check `output/<run-id>/events.jsonl` for the missing record (jsonl always lands) |
| Span shows up but agent_name tag missing | Agent path bypasses `traced_agent_run` (rare — direct `agent.run()`) | Per-agent instrumentation skipped | Wrap the call with `traced_agent_run` |

The pipeline NEVER raises from observability code. If Logfire is down,
the run still produces a paper, and the events.jsonl on disk is the
canonical record.

---

## Debug runbook: missing trace

You expected to see a span in Logfire and it isn't there. Steps:

1. **Check the events.jsonl record exists**:
   ```bash
   grep '<event_type>' output/<run-id>/events.jsonl | tail -1
   ```
   If the line is missing, the event itself never emitted — bug is in the
   emitter, not observability.

2. **Confirm the event type is span-enriched**. Only the 5 types in
   `_SPAN_ENRICHED_EVENT_TYPES` (recovery_event, doi_gate_failure,
   cascade_verdict, novelty_gate_verdict, ethics_checklist_result) emit
   parallel Logfire spans. Legacy types only land in events.jsonl.

3. **Verify Logfire wiring**. Look at startup logs for the tracing-health
   line. If `status=token-absent`, set `LOGFIRE_TOKEN`. If absent
   entirely, the pipeline crashed before `configure_observability`.

4. **Check Logfire project**. Are you searching the `research-demo` project
   (per OQ18)? Different account / different project = no results.

5. **Pull the events.jsonl `error_code`**. The span carries the same
   `error_code` field per AP37 — search Logfire with that exact string.

6. **Check Logfire quota / backend status**. If `enabled` health line +
   no spans for the whole run, the backend is failing silently.

---

## Swap the Logfire project

To move traces to a different project (e.g. for a fresh experiment cohort
isolated from production):

1. Update the `_LOGFIRE_PROJECT` constant in
   `src/academic_pipeline/observability.py`:
   ```python
   _LOGFIRE_PROJECT = "research-demo-staging"
   _LOGFIRE_DASHBOARD_URL = f"https://logfire-us.pydantic.dev/yzxbiz/{_LOGFIRE_PROJECT}"
   ```
2. Update OQ18 in `docs/PRD.md` §29 to point at the new project name (the
   PRD is the contract; if you change the default, the PRD has to know).
3. Issue a new `LOGFIRE_TOKEN` scoped to the new project and rotate it
   into your environment.
4. Re-run the pipeline. The tracing-health line will print the new
   project + dashboard URL on startup; spans will appear in the new
   project's view.

The `service_name="academic-pipeline"` value in `logfire.configure()`
is independent of the project — leave it alone unless the new project
also wants to host traces from a different service.

---

## See also

- `src/academic_pipeline/observability.py` — `configure_observability`,
  `_LOGFIRE_PROJECT`, `_LOGFIRE_DASHBOARD_URL`, `install_keepalive_provider_patch`.
- `src/academic_pipeline/runtime/events.py` — `EventLogger`,
  `_SPAN_ENRICHED_EVENT_TYPES`, `_emit_event_span`.
- `src/academic_pipeline/runtime/trace_logger.py` — `traced_agent_run`,
  `_instrument_agent_once`, per-agent instrumentation set.
- PRD §17 — error code namespaces (DSH, REC, REN, CAS, NOV, ETH, ...).
- PRD §18 — full events.jsonl schema reference.
- [docs/architecture/recovery.md](./recovery.md) — watchdog layers that
  emit `recovery_event` records.
