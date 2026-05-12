# Skill Packs

PydanticAI agents in this pipeline reach domain knowledge (AutoGluon API tables,
Exa search call patterns) through **skill packs** — bundles of Markdown +
optional script files loaded at agent construction time and surfaced as
on-demand context.

This document describes the loading contract, the on-disk layout, and the two
packs that ship with v2.5.0.

## Loading contract

`src/academic_pipeline/config.py` exposes a single module-level constant:

```python
PROJECT_ROOT = Path(__file__).parent.parent.parent  # repo root
SKILLS_DIRS  = [str(PROJECT_ROOT / "skills")]
```

Each agent registry that wants pack access constructs a
`pydantic_ai_skills.SkillsCapability` with `directories=SKILLS_DIRS`:

```python
from pydantic_ai_skills import SkillsCapability
from academic_pipeline.config import SKILLS_DIRS

SkillsCapability(directories=SKILLS_DIRS)
```

Consumers today: `research/agents.py`, `review/agents.py`, `experiment/agents.py`,
`writing/agents.py`. Agents that don't need pack access (e.g. `runtime/evaluator.py`)
simply omit the capability.

`SkillsCapability` discovers packs by recursive `SKILL.md` lookup under each
listed directory (default depth limit = 3). Discovery is silent on missing or
unreadable directories; failures surface only when an agent run actually invokes
a skill that wasn't loaded.

## Pack contract

A pack is a directory containing exactly one `SKILL.md` and any number of
sibling files referenced from that markdown.

`SKILL.md` must start with YAML frontmatter delimited by `---` lines:

```markdown
---
name: <pack-id>
description: <one-paragraph summary the model uses to decide whether to consult the pack>
---

# Free-form markdown body
```

| Field         | Required | Notes                                                                    |
| ------------- | -------- | ------------------------------------------------------------------------ |
| `name`        | yes      | Pack identifier. Conventionally matches the directory name.              |
| `description` | yes      | Routing summary surfaced to the LLM when deciding which packs to invoke. |

Sibling files (Python helpers, JSON snippets, etc.) live next to `SKILL.md`
and are referenced by relative path from the markdown body.

## Shipped packs

### `skills/autogluon/SKILL.md`

7.2 KB reference covering `TabularPredictor`, `TimeSeriesPredictor`, and
`MultiModalPredictor` — presets, `eval_metric` choices, sample weights,
inference patterns, and figure-generation snippets. Consumed by the experiment
subgraph's `ml_engineer` and `config_writer` agents at codegen time.

### `skills/exa-research/SKILL.md`

1.5 KB quick reference for the two direct Exa Python tools
(`web_search_exa`, `web_fetch_exa`). Documents typical query shapes, the
`category="research paper"` filter, and similar-paper lookup by URL. Consumed
by the bibliography and experiment-designer agents.

## Adding a new pack

1. Create `skills/<new-pack>/SKILL.md` with frontmatter (`name`, `description`).
2. Drop any helper files alongside.
3. Add a unit test in `tests/unit/test_config.py` asserting the pack is
   discovered (mirror `test_both_skill_packs_load_via_skills_capability`).
4. No `config.py` change required — discovery is directory-based.

## Verification

```bash
uv run pytest tests/unit/test_config.py -k 'skills_dirs or skill_pack' -x -q
```

Two tests guard the loading contract: one checks every entry in `SKILLS_DIRS`
resolves on disk, the other checks both shipped packs are discoverable and
have the required frontmatter fields. PRD §6.12.T8.
