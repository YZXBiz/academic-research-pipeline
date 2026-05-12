# Release & CI/CD

How the academic-pipeline ships to PyPI, what runs in CI, and which secrets
the workflows need. Source-of-truth for `.github/workflows/*` audits.

PRD anchor: §6.14.

## `.github/workflows/publish.yml` audit (PRD §6.14.T2)

**State at audit (2026-05-06):** working as intended. Not broken, not vestigial,
no rewrite needed before the v2.5.0-rc tag.

```yaml
name: Publish to PyPI
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    runs-on: self-hosted
    permissions:
      id-token: write  # Required for trusted publishing (OIDC)
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

| Field | Value | Notes |
|---|---|---|
| Trigger | `push` of any tag matching `v*` | Operator pushes `vX.Y.Z` to fire. |
| Runner | `self-hosted` | Same runner pool as `ci.yml` (PRD §6.14.T5). |
| Build | `uv build` | Produces `dist/*.whl` + `dist/*.tar.gz`. |
| Registry | PyPI | Default target of `pypa/gh-action-pypi-publish`. |
| Auth | OIDC trusted publishing (`id-token: write`) | No PyPI token needed; the workflow exchanges its short-lived OIDC ID-token for an upload credential at PyPI. PyPI side requires the project to be configured with this repo + workflow as a trusted publisher (one-time setup at https://pypi.org/manage/account/publishing/). |

The OIDC path is the modern, recommended pattern — the alternative
`PYPI_TOKEN` secret would be a long-lived credential and is intentionally
NOT used here.

**No CHANGELOG-as-release-body wiring today.** PRD §6.14.T2 listed this as
optional ("if broken or vestigial, replace with tag-triggered GitHub Release
that uploads `dist/*` and renders CHANGELOG entry as release body"); since
the workflow already publishes to PyPI cleanly, the GitHub Release step is
a Phase 2 enhancement, not a Phase 1 blocker. Tracked as a follow-up if
operators want richer release notes than the auto-generated PyPI one.

## `.github/workflows/ci.yml` (existing)

Runs on every push to `main` and every PR targeting `main`. Concurrency
key cancels in-progress runs on the same branch when a new push lands.

Jobs (audit at 2026-05-06):

| Job | What it runs | Notes |
|---|---|---|
| `version-consistency` | `uv run python tools/check_version_consistency.py` | §6.14.T3 — required per-PR; pairs with §6.12.T6. |
| `pre-commit` | `pre-commit run --all-files --show-diff-on-failure` | §6.14.T4 — same hooks contributors get locally (ruff, format, trailing-whitespace, etc.). |
| `lint` | `uv run ruff check src/ tests/` | Self-hosted runner. |
| `typecheck` | `uv run basedpyright src/academic_pipeline/` | §6.14.T7 reconciled — Makefile, pyproject dev dep, CI, and pyrightconfig.json all agree on basedpyright. |
| `test` | `uv run pytest tests/` (matrix Py 3.12 + 3.13, gated on lint+typecheck) | Small marker only (medium tests gated separately in `test-medium`). |
| `test-medium` | `make test-integration` (= `pytest -m medium`) | §6.14.T1 — Docker integration tests; gated on lint+typecheck; skipped on fork PRs. |
| `security` | `uv run pip-audit` + `uv run bandit -r src/ --severity-level medium` | §6.14.T8 — bandit blocks on medium+; 35 low-severity informational findings stay non-blocking. |

All Phase 1 §6.14 jobs are now wired. Phase 2+ may layer additional
checks (per-PR coverage gate, mutation testing, etc.).

## Self-hosted runner secret model (PRD §6.14.T5)

The CI + publish workflows run on a self-hosted runner (single node managed
by Jackson). Secrets reach the workflow steps via standard GitHub
`secrets.*` references — they are configured at *Settings → Secrets and
variables → Actions* on the repository. The self-hosted runner itself
holds nothing sensitive on disk; secrets are injected per-step by GitHub's
runner agent at job start and unset on job end.

### Secret inventory

| Name | Required by | Workflow refs | Source |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `test`, `test-medium` | `ci.yml:83`, `ci.yml:104` | Anthropic console |
| `EXA_API_KEY` | `test-medium` | `ci.yml:105` | Exa dashboard |
| `LOGFIRE_TOKEN` | (planned: `test-medium` once `pydantic-logfire` is exercised in CI) | none today | Logfire project settings |
| `S2_API_KEY` | (planned: bibliography integration tests) | none today | Semantic Scholar API |
| `PYPI_TOKEN` | **NOT NEEDED** — `publish.yml` uses OIDC trusted publishing | n/a | n/a |

`LOGFIRE_TOKEN` and `S2_API_KEY` are slotted but not wired into any
workflow step today. Add them to the `env:` block of `test-medium` only
when a test path actually consumes them; unused secrets are still rotated
on the schedule below to prevent latent-credential rot.

### Provisioning runbook

1. Open *Settings → Secrets and variables → Actions* on the repo.
2. Under **Repository secrets**, click *New repository secret*.
3. Name field uses uppercase + underscores matching the inventory above.
4. Paste the credential body (no leading/trailing whitespace).
5. Click *Add secret*. The value is one-way — GitHub will never display
   the plaintext again; rotate by replacing.
6. Reference from a workflow step's `env:` block as
   `${{ secrets.SECRET_NAME }}`.

### Rotation schedule

| Cadence | Secret(s) | Trigger |
|---|---|---|
| 90 days | `ANTHROPIC_API_KEY`, `EXA_API_KEY`, `S2_API_KEY` | Calendar reminder (Jackson). |
| 90 days | `LOGFIRE_TOKEN` | Same calendar entry; rotate even if unused in CI. |
| On role change | All | Whenever the operator who provisioned a key leaves the project. |
| On suspected exposure | All affected | Immediate revoke + reissue + audit `gh api repos/.../actions/secrets` for last-used timestamps. |

### Fork-PR safety

`secrets.*` resolves to empty strings on PRs from forks (GitHub's standard
guard against credential exfiltration). The `test-medium` job adds an
explicit same-repo guard via `github.event.pull_request.head.repo.full_name
== github.repository`, so it skips entirely on fork PRs rather than
running with empty credentials and failing with confusing error messages.

### What is NOT a secret

- `pyproject.toml::version`, `VERSION`, README badges — read by
  `version-consistency` from the repo, no auth needed.
- The OIDC ID-token used by `publish.yml` — a short-lived (~10 min) token
  exchanged at PyPI for an upload credential. PyPI side requires one-time
  configuration as a trusted publisher (https://pypi.org/manage/account/publishing/);
  no long-lived token needs to live in repo secrets.

## Tag protection (PRD §6.14.T6)

GitHub tag protection prevents accidental pushes of release tags by anyone
who is not an explicit maintainer. Without it, anyone with `push` access
to the repo could fire `publish.yml` by tagging an arbitrary commit `vX.Y.Z`
— a small but real PyPI-publishing risk on a self-hosted runner.

**Status:** runbook below; the GitHub UI configuration step itself is
operator-only (no in-repo config can express it). After Jackson applies
the rule once, this section becomes audit history.

### Operator runbook (one-time setup)

1. Open *Settings → Tags* on the GitHub repository.
2. Click *Add rule*.
3. **Tag name pattern:** `v[0-9]+.[0-9]+.[0-9]+`
   - Matches semantic-version tags like `v2.5.0`, `v2.5.1-rc1` (rc / dev
     suffixes still match the prefix portion).
   - Does NOT match arbitrary tag pushes like `experiment-2026-05`.
4. Under *Restrict creators*, add the maintainer set (Jackson + any future
   release manager). All other accounts will be denied tag creation.
5. Save the rule. The setting takes effect immediately for new tags;
   existing tags are unaffected.

### Verifying the rule is live

After the rule is applied, a non-maintainer attempting `git push origin v9.9.9`
must see:

```
remote: error: GH013: Tag protection rule prevents tag creation: vX.Y.Z by user not in allowlist
```

A maintainer's `git push origin vX.Y.Z` succeeds normally and triggers
`publish.yml`.

### What this does NOT cover

- Tag deletion: GitHub tag-protection rules block creation but not
  deletion. Once a tag is pushed it lives in the registry until manually
  deleted (a separate UI step). For PyPI, releases are immutable anyway —
  deleting the tag does not pull the release back.
- Branch pushes to `main`: covered separately by branch protection rules
  (also operator-only). The pre-commit hook `no-commit-to-branch --branch
  main` is honor-system locally; branch protection on the GitHub side is
  the real gate.
- Force-push of an existing tag: also blocked by the same rule, since
  re-creation of the tag is treated as a new creation event.

## Release procedure (today)

1. All Phase 0 + Phase 1 work merged to `main`.
2. CHANGELOG.md updated under a new `[X.Y.Z] — YYYY-MM-DD` heading (move
   `[Unreleased]` content down).
3. `VERSION`, `pyproject.toml::version`, README badges all read `X.Y.Z`
   (verified by `tools/check_version_consistency.py`).
4. Maintainer creates and pushes the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. GitHub Actions runs `publish.yml`, which builds `dist/*` and uploads
   to PyPI via OIDC trusted publishing.
6. Verify the new version appears at https://pypi.org/project/academic-pipeline/.
