---
name: run-and-monitor
description: Start a full pipeline run (with experiment) in the background and dispatch two monitoring subagents — one tracking progress/status from logs, one incrementally inspecting MD artifacts for quality and structure. Use when the user wants to kick off a paper and have it actively monitored for problems.
---

# Run + Dual-Monitor Pipeline

## When to use

User says anything like:
- "start a new run and monitor it"
- "kick off a full pipeline run with monitoring"
- "run a paper and watch the progress"
- "fire up a pipeline with the two-agent monitor"

## What this does

Runs the full pipeline in background, then dispatches **two parallel subagents**:

1. **Progress monitor** — tails the log, tracks node completions, stage transitions, errors. Reports status periodically.
2. **MD quality auditor** — periodically inspects new MD files in `output/<thread-id>/` (research traces, drafts, synthesis docs) and rates each on quality, structure, and adherence to the intended pipeline plan.

## Steps

### 1. Confirm topic

If user didn't specify a topic, ask. Should be:
- Specific enough for a real paper (not "AI in healthcare")
- Has public datasets if `--force-experiment` is on (sklearn, ucimlrepo, HuggingFace)
- Falls within Jackson's domain interest if no other signal (healthcare DS, publications)

### 2. Kick off the run in background

```bash
make run-experiment TOPIC="<topic>" 2>&1 | tee /tmp/pipeline-run.log
```

Run with `run_in_background: true`. Capture the bash task ID for later monitoring.

The pipeline auto-generates a thread-id like `run-MMDD-HHMM_xxxx`. The first ~10 seconds of log will show it. Capture this — both monitor agents need it.

### 3. Wait for output dir to exist

The pipeline creates `output/<thread-id>/` and the symlink `output/latest/` after IntakeNode. Poll `ls output/latest/` until it exists (usually within 30 seconds).

### 4. Set up persistent Monitor (NOT a subagent — they're one-shot)

**Critical lesson learned:** Subagents can't sleep-and-check across turns. They run once, report, then exit. For continuous monitoring, use the **Monitor tool** (which streams stdout lines as events) plus **on-demand subagent re-dispatch** when milestones fire.

#### Persistent Monitor (controller, NOT subagent)

```
Monitor tool, persistent: true, timeout_ms: 3600000, command:
tail -F /tmp/pipeline-run.log 2>/dev/null | grep --line-buffered -E "(\[research\]|\[experiment\]|\[writing\]|\[review\]|\[integrity\]|\[pre_integrity_|\[final_integrity_).+ completed$|set_stage|Pipeline failed|Traceback|Resuming .+ subgraph|PIPELINE COMPLETE|integrity FAIL|integrity PASS|aborting"
```

Each matching line becomes a notification. The controller (you) re-dispatches the MD auditor on each milestone event.

#### MD Quality Auditor — re-dispatched on each milestone

When the Monitor fires a notification (e.g., "[research] SynthesisNode completed"), dispatch a fresh subagent to audit the NEW files only:

```
subagent_type: general-purpose
description: Audit new MD files

prompt:
A new pipeline node just completed: <node name from monitor event>.

Output dir: /Users/c839755/Desktop/academic-pipeline/pydanticai/output/latest/
Thread ID: <thread-id>

Find new or modified .md files since the last check:
```bash
find output/latest/ -name "*.md" -newer /tmp/last-md-check -type f 2>/dev/null
touch /tmp/last-md-check
```

For each new/updated file, rate:
a) Quality (1-10) — PhD-grade or lit review?
b) Structure — required sections present?
c) Plan adherence — matches expected output for this pipeline stage?

Read the rubric: /Users/c839755/Desktop/academic-pipeline/pydanticai/.claude/skills/run-and-monitor/quality-rubric.md

Report format per file:
- path | Q:N/10 | Struct:PASS/FAIL | Plan:PASS/FAIL | "one-line note"

ESCALATE IMMEDIATELY if you find:
- TODO/TBD/placeholder content
- Fabricated citations or DOIs
- Section content < 100 words when rubric expects 500+
- Reads as lit review (Jackson's #1 historical concern)

Be terse. Under 200 words total.
```

### 5. Stay available for user questions

While Monitor and audits run, keep context free for user interaction. Forward latest events on request.

### 6. On completion

When the pipeline finishes:
1. Read `output/latest/dashboard.txt`
2. Read final `output/latest/paper.md` (last 100 lines for the conclusion + references)
3. Synthesize: total time, token usage, key quality findings from MD auditor, any errors caught by progress monitor
4. Offer: "Paper ready at `output/latest/paper.pdf`. Want me to read it through, or invoke `/revise-paper` for revisions?"

## Failure modes

- **Pipeline stalls (no API calls for 10+ min):** Progress monitor escalates. Tell user the proxy probably dropped SSE. They can `make resume THREAD_ID=<id>` after Ctrl+C.
- **Quality auditor finds shallow content:** Surface the concern early — better to know mid-run than after 80 min.
- **Docker container conflicts:** If experiment phase fails with "container already exists", run `docker rm -f experiment-*` and resume.

## Resources

- `monitor-checks.md` — full list of grep patterns and thresholds (referenced by subagent 1)
- `quality-rubric.md` — detailed rubric for MD auditor (referenced by subagent 2)
