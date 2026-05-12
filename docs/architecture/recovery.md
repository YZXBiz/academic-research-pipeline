# Recovery Layers

Defense-in-depth against the LLM-pipeline failure modes that wedge a process
for 1h+ instead of erroring out: silent TCP drops by LLM proxy's proxy, blocked
synchronous `recv()` under the async facade, asyncio tasks that never resume,
and runaway crash loops. Each layer below catches a different class of hang;
together they bound the worst-case wall-clock penalty for any single failure.

PRD anchor: §6.6 (Hang recovery).

## L1 — TCP keepalive (transport)

`src/academic_pipeline/recovery/transport.py` exposes a cross-platform
`httpx.AsyncClient` factory that sets socket-level `TCP_KEEPALIVE` (`60s`
idle, `15s` interval, `4` retries). Without this, macOS' default `keepidle`
is 2 hours, and the LB silently drops idle SSE streams without sending
`FIN/RST`; the SDK's synchronous `recv()` then blocks indefinitely under
the async facade. Pattern adapted from `shigechika/mcp-stdio` PR #34 (Apr
2026). All HTTP-issuing agents share the singleton `_SHARED_KEEPALIVE_CLIENT`
(PRD AP67 — never construct per-agent clients).

**Catches:** silent proxy drops, NAT-layer connection eviction.
**Doesn't catch:** drops during the keepidle window before the first probe,
LLM legitimately thinking for >max_idle.

## L2 — bounded_run (per-call wall-clock cap)

`src/academic_pipeline/recovery/bounded_run.py::bounded_agent_run()` wraps
`agent.run(...)` in `asyncio.wait_for(..., timeout_s=900)` so a single
agent call cannot exceed 15 minutes. Generic over the agent's deps and
output types so callers preserve type safety end-to-end. The bound is the
upper limit on a single LLM call's "legitimate slow" budget.

**Catches:** runaway thinking, infinite tool-call loops inside a single
agent run.
**Doesn't catch:** blocked-in-kernel `recv()` (asyncio cannot preempt a
sync syscall), inter-call hangs between `agent.run()` calls.

## L3 — Heartbeat thread (proof-of-life)

`src/academic_pipeline/recovery/heartbeat.py` runs a daemon thread that
atomically writes a wall-clock timestamp to `output/<run_id>/heartbeat.txt`
every 10s. **Critical:** must be a thread, not an `asyncio.create_task` —
when the event loop is blocked in synchronous `recv()`, asyncio tasks
do not fire and the watchdog would false-positive on a recovering pipeline.
A daemon thread runs regardless of event-loop state. Atomic write via
`.tmp` + rename so the watchdog never reads a half-written file.

**Catches:** nothing on its own — it is the input signal for L4.

## L4 — Watchdog process (kill + auto-resume)

`src/academic_pipeline/recovery/watchdog.py` is a sibling subprocess that
polls `events.jsonl` mtime as the proof-of-progress signal. If the log is
stale beyond `--max-idle` (default 600s = 10 min), it sends `SIGTERM` to
the pipeline's process group via the `.pgid` file, waits 10s, then
`SIGKILL` if still alive. Optionally invokes `make resume` to relaunch.
A 3-strikes escalation aborts the run if recoveries do not advance
events.jsonl (configurable via `--max-recoveries N`, PRD §6.6.T1).

**Why mtime, not heartbeat:** the heartbeat thread keeps ticking even when
the main code is hung in `await` (verified failure mode in
`run-0504-1212_cf0d` — 1h41m wedged with a fresh heartbeat). Only
events.jsonl proves the pipeline made real *node-level* progress.

**Catches:** anything below the per-call timeout that L2 missed —
inter-call hangs, deadlocks, runaway loops, OOM-stalled subprocesses.

## Composition: `make run-experiment` + supervisor

`src/academic_pipeline/recovery/supervisor.py::supervised_run()` is the
single entry point that composes all four layers:

1. Forks the pipeline as subprocess A with `os.setsid` (own pgid).
2. Polls `output/latest/events.jsonl` for the first `pipeline_start`
   event to learn the run's `thread_id`.
3. Forks the watchdog as subprocess B (own pgid, `--auto-resume`,
   `--max-recoveries N`).
4. Logs loudly if B dies before A — pipeline is unprotected from that
   point.
5. Returns A's final exit code (signal exit codes propagate through —
   e.g. `-15` after `SIGTERM` from the watchdog).

CLI surface: `make run-experiment TOPIC="..."` is the operator-friendly
wrapper; `python -m academic_pipeline supervised-run "topic" --max-recoveries N`
is the explicit form.

## Failure-mode coverage matrix

| Class                                    | L1 | L2 | L3 | L4 |
| ---------------------------------------- | -- | -- | -- | -- |
| LLM proxy silent SSE drop           | ✓  |    |    | ✓  |
| Single LLM call thinking >15min          |    | ✓  |    |    |
| Inter-call hang between agent.run()      |    |    |    | ✓  |
| Tool-loop runaway inside one agent       |    | ✓  |    |    |
| Subprocess deadlock (e.g. Docker exec)   |    |    |    | ✓  |
| Crash loop after kill+resume (3-strikes) |    |    |    | ✓  |

L3 has no row because it is purely an input signal for L4.

## Recovery events on disk

L4 emits 5 typed events to `events.jsonl`: `watchdog_killing`,
`watchdog_killed`, `watchdog_resuming`, `watchdog_resumed`,
`watchdog_aborted`. PRD §6.6.T2 adds a generic `recovery_event` shape
(`{layer, action, reason, strike, error_code: "REC###"}`) covering L1-L3
which currently emit nothing. The 5 specific types remain alongside the
generic one for backward compat with Logfire saved searches (do NOT
delete them — PRD AP18).

## Debugging a recovery loop

1. **Find the run dir:** `ls -t output/ | head -3`.
2. **Tail the event log:** `tail -F output/<thread_id>/events.jsonl |
   grep watchdog_` — every kill/resume cycle logs there.
3. **Check the watchdog stdout:** the supervisor redirects watchdog
   stdout/stderr to `DEVNULL`, but you can re-run it standalone:
   `python -m academic_pipeline watchdog <thread_id> --max-idle 60
   --max-recoveries 5` to see live output.
4. **Process tree:** `ps -A -o pid,pgid,ppid,command | grep
   academic_pipeline` — verify both pipeline pgid and watchdog pid are
   alive. If watchdog died first, supervisor logs `WATCHDOG DIED` to
   stderr (then the pipeline is unprotected).
5. **3-strikes hit:** look for `watchdog_aborted` event. The watchdog
   gives up if N consecutive recovery cycles failed to advance
   events.jsonl. Bump `--max-recoveries` for legitimately-slow runs;
   investigate the underlying hang otherwise.
6. **Heartbeat sanity:** `stat output/<thread_id>/heartbeat.txt` — mtime
   should be fresh (<10s old) on a live run. Stale heartbeat with stale
   events.jsonl = pipeline truly dead. Fresh heartbeat with stale
   events.jsonl = the exact failure mode L4 was built for (event loop
   blocked but the heartbeat daemon thread still ticks).

## Related files

| Path                                     | Role                                           |
| ---------------------------------------- | ---------------------------------------------- |
| `recovery/transport.py`                  | L1 — keepalive httpx client                    |
| `recovery/bounded_run.py`                | L2 — per-call wall-clock cap                   |
| `recovery/heartbeat.py`                  | L3 — daemon-thread proof-of-life               |
| `recovery/watchdog.py`                   | L4 — sibling kill+resume process               |
| `recovery/process_state.py`              | `.pgid` file, ProcessLock                      |
| `recovery/supervisor.py`                 | Composition + `supervised_run()` entry point   |
| `cli.py::watchdog_cmd`                   | `--max-recoveries N` CLI surface (§6.6.T1)     |
| `cli.py::supervised_run_cmd`             | `--max-recoveries N` CLI surface (§6.6.T1)     |
| `runtime/events.py`                      | event_logger emit hooks (recovery_event TBD)   |
| `tests/integration/test_hang_recovery_e2e.py` | End-to-end recovery tests (§6.6.T4)        |
