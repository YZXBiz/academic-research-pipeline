# Documentation Index — v2.5.0

The canonical entry point for all project documentation. Doc builds remain
ad-hoc in v2.5.0 — `mkdocs` packages are declared as dev dependencies but no
`mkdocs.yml` is wired (see PRD §6.14.T9; deferred to v2.6.0+).

## Contract

The PRD is the authoritative project contract. Every other doc here exists to
amplify or operationalize a specific PRD section.

| Doc | What it is |
|---|---|
| [`PRD.md`](PRD.md) | The contract. 446K, 3,391 lines, 167 verified iterations. Never edit during a Ralph loop. |

## Architecture references

Per-subsystem docs that consumers (humans + agents) read before touching a
component. Each is ≤200 lines; deeper detail lives in `superpowers/specs/`.

| Doc | What it covers | PRD anchor |
|---|---|---|
| [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md) | High-level system architecture reference | §6 overview |
| [`architecture/architecture.{excalidraw,svg,png}`](architecture/) | System-wide diagram (Excalidraw source + exports) | §6 |
| [`architecture/pipeline-architecture.{drawio,png}`](architecture/) | Pipeline subsystem diagram (drawio source + export) | §6.1–§6.7 |
| [`architecture/recovery.md`](architecture/recovery.md) | 4 hang-recovery layers (transport, bounded_run, heartbeat, watchdog) + debug runbook | §6.6 |
| [`architecture/release.md`](architecture/release.md) | publish.yml + ci.yml audit, OIDC trusted publishing model, secrets, tag protection | §6.14 |
| [`architecture/sdk.md`](architecture/sdk.md) | Public Python API surface (Pipeline, PipelineConfig, PipelineResult, DEFAULT_CONFIG) | §6.12 |
| [`architecture/skills.md`](architecture/skills.md) | `SKILLS_DIRS` loading, SKILL.md frontmatter, shipped packs | §6.12.T8 |
| [`architecture/TRACEABILITY.md`](architecture/TRACEABILITY.md) | Trace token producer/transport/consumer seams | §6.10 |
| [`architecture/TRACEABILITY_RUNBOOK.md`](architecture/TRACEABILITY_RUNBOOK.md) | Operator runbook for traceability incidents | §6.10 |

Coming in later v2.5.0 phases (placeholder rows referenced by Phase 1+ tasks):

| Doc | When it lands | PRD anchor |
|---|---|---|
| `architecture/observability.md` | Phase 2 §6.13.T4 | §6.13 |
| `architecture/traceability.md` (revision) | §6.10.T7 | §6.10 |

## User-facing docs

Short feature-specs the operator (Jackson) reads before invoking a feature.

| Doc | What it covers |
|---|---|
| [`user/resume.md`](user/resume.md) | `make resume THREAD_ID=X` workflow + invariants |
| [`user/impressive.md`](user/impressive.md) | Marketing-grade summary of pipeline outputs |

## Superpowers (specs + plans)

Living design + implementation history. Specs propose mechanisms; plans expand
specs into Ralph-iterable task lists. Both directories are local-only and
gitignored — they exist for the active loop only.

| Path | Role |
|---|---|
| `superpowers/specs/` | Design specs (one per major mechanism, e.g. SCI traceability port) |
| `superpowers/plans/` | Implementation plans (one per spec; expanded by sr-writing-plans) |

## Project root

Top-level docs the build system (Makefile, CI, packaging) consume directly:

- [`../README.md`](../README.md) — repo entry point
- [`../.claude/CLAUDE.md`](../.claude/CLAUDE.md) — agent operating instructions (project-scoped)
- [`../CHANGELOG.md`](../CHANGELOG.md) — versioned release notes
- [`../VERSION`](../VERSION) — single source of truth for `pyproject::version` and README badges (PRD §6.12.T6)

## Conventions

- All `.md` files are GFM (GitHub-flavored Markdown) with relative links from
  the file's own directory.
- Headings start at `##` (the H1 is the doc title only).
- New per-subsystem docs go under `architecture/` and stay ≤200 lines; deeper
  rationale belongs in a `superpowers/specs/` design doc.
