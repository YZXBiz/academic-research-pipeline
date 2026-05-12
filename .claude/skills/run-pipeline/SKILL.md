---
name: run-pipeline
description: Run the academic research pipeline to produce a paper from a topic. Use when the user asks to write a paper, run research, or generate academic content. Handles running the CLI, monitoring via Logfire, and presenting output.
---

# Run Academic Pipeline

## When to use
User says anything like: "write a paper on X", "run the pipeline", "research X", "generate a paper about X"

## Steps

1. **Confirm the topic** with the user if not explicit

2. **Generate a thread ID** (short, descriptive, e.g., `ml-demand-forecasting`)

3. **Run the pipeline** in background:
```bash
uv run python -m academic_pipeline.cli run "<topic>" --thread-id <id> --output-dir output -v
```

4. **Set up Logfire monitoring** — create a /loop to check every 5 minutes:
- Query `research-demo` project for errors/exceptions
- Report node completions and progress
- Flag stalls (no new spans for 10+ minutes)

5. **When complete**, read and summarize the output:
```bash
cat output/dashboard.txt
```
Then offer: "The paper is ready. Want me to read through it, or do you have specific feedback?"

## If the pipeline stalls
The proxy drops SSE connections after ~10 minutes on some requests. If no new Logfire spans for 10+ min:
1. Tell the user the pipeline stalled
2. They need to Ctrl+C the stuck process
3. Restart with same thread-id (crash recovery resumes from last node)

## If the user wants revision after reading
Invoke the `/revise-paper` skill instead.
