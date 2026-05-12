---
name: revise-paper
description: Revise a pipeline-generated paper based on user feedback. Use when the user wants to change, fix, or improve parts of a generated paper. Determines whether to edit files directly or re-run the pipeline with --revision flag.
---

# Revise Paper

## When to use
User says anything like: "fix the methodology", "the intro is too long", "add more sources", "this section is weak", "change X to Y"

## Decision: Surface edit vs Structural change

### Surface edit (edit files directly)
- Rewriting a paragraph or section for clarity/tone
- Fixing typos, grammar, formatting
- Adding/removing a specific paragraph
- Shortening or expanding a section

Action: Read the file from `output/`, edit it with the Edit tool, done.

### Structural change (re-run pipeline with --revision)
- Changing the methodology approach
- Switching from qualitative to quantitative
- Adding an entirely new research angle
- Fundamentally rethinking the argument structure
- "The whole approach is wrong"

Action:
```bash
uv run python -m academic_pipeline.cli run "<same topic>" \
  --thread-id <same-id> \
  --revision "<user's feedback verbatim>"
```
Then monitor via Logfire until complete.

## Steps

1. **Read the current paper**: `cat output/paper_draft.md` (or whichever file is relevant)

2. **Assess the feedback**: Is this a surface edit or structural change?

3. **If surface**: Edit the file directly. Show the user the diff.

4. **If structural**: Explain that this requires a full re-run (~1-2 hours) and confirm before starting. Then run with `--revision` flag and monitor.

5. **If unclear**: Ask the user — "Is this a wording change or do you want to fundamentally change the approach? Wording I can fix in 30 seconds. Fundamental change means re-running the pipeline (~1-2 hours)."

## Important
- Always read the current output before making changes
- For surface edits, show a before/after summary
- For structural changes, the --revision flag injects the feedback into every agent's prompt
- The pipeline will re-run from scratch but guided by the revision instructions
