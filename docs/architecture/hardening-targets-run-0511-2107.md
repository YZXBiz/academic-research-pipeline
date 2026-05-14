# Hardening targets — post-mortem from run-0511-2107_6271

**Run context:** Topic `"how data scientists do software testing"`, DeepSeek-v4-pro
via official API, `reasoning_effort: max` on 14 review-class agents. Ran to
pre_integrity (3rd fix-loop iteration), then died on a serialization 400. Did
not reach the review-phase gauntlet.

The findings below are the load-bearing diagnostic. Everything else from this
run (citation hygiene, RQ framing, bibliography content) was clean.

## Status (2026-05-14)

All four hardening bugs are addressed plus the dominant failure class:

- **citation_grounding** — new writing-phase agent + parser + models, wired
  into the integrity gate as a hard FAIL on contradicts/unsupported verdicts.
  Closes the dominant failure class (citations not matching their source).
- **Bug 1** (severity inversion) — mitigated structurally: the deterministic
  `placeholder_scan` and the new `discussion_results_consistency` gate force
  FAIL without relying on the LLM's severity classifier at all.
- **Bug 2** (Discussion-vs-Results) — new `discussion_results_consistency.py`
  deterministic scanner, wired into IntegrityCheckNode as Layer 4b.
- **Bug 3** (Phase E sampling) — `integrity_verification.yaml` sampling floor
  raised; numeric / framework-attribution / Abstract+Results+Discussion claims
  now mandatory-full-verify.
- **Bug 4** (methodology-aware compliance) — new `reporting_guidelines.py`
  routes the compliance check to PRISMA/CHERRIES/STROBE/CONSORT by detected
  study design.

Infra findings below (timeouts, CrossRef) were handled in the 2026-05-12/13
commits. The PydanticAI ↔ DeepSeek message-serialization 400 — the bug that
actually ended run-0511-2107 — is now fixed: `install_deepseek_message_patch`
in `observability.py` coerces `content=None` to `""` on thinking-only
assistant turns so DeepSeek's validator accepts them. **All run-0511-2107
findings are now resolved.**

## What the gates caught (citation hygiene — strong)

The PreIntegrityNode classifier reliably catches structural citation defects:

- Dangling references (cited in body, missing from bib)
- Orphan references (in bib, never cited)
- Context-mismatch citations (s011 Pruim coding-best-practices cited as if it
  validated a TAM testing instrument — caught as MEDIUM)
- FM7 "Reproducibility Theater" failure-mode pattern
- AI-text stylistic heuristics (em-dash density, paragraph-length CV=0)
- Bibliographic staleness (arXiv preprint → published TOSEM)

## What the gates missed (semantic integrity — real gaps)

Surface checks pass; semantic checks fail. The failure modes the run produced
were exactly the ones the gates need to grow into.

### Bug 1: severity classifier inverts MINOR vs CRITICAL

`integrity_verification` scanned the merged draft and **correctly enumerated
116 `[PENDING: N/β/SD/r/p/...]` instances** in the Results section — then filed
the finding as `MINOR #4`. A paper with no numeric results in its Results
section is unpublishable; this should be CRITICAL.

**Fix target:** `src/academic_pipeline/integrity/specs/integrity_verification.yaml`.
Add a hard rule: `[PENDING:]` density ≥ 5 in any section ⇒ CRITICAL. The
existing severity rubric appears to weight novelty of finding over magnitude
of defect.

### Bug 2: no "Discussion-vs-Results consistency" check

The Discussion section confidently interpreted non-existent results — e.g.
*"the effect size was moderate"*, *"the correlation was robust and persistent"*
— while the Results section's same metrics were `[PENDING:]` placeholders.
None of the gates flagged this. The integrity report's
`statistical_data_accuracy` row read only `N/A (Results section entirely
[PENDING:] placeholder)`.

**Fix target:** new sub-check in `integrity_verification` that pairs each
quantitative claim in Discussion (`r`, `p`, `β`, `effect size`, `power`,
direction words like *moderate / robust / persistent*) with a cite back to a
non-PENDING value in Results. Unmatched claims → CRITICAL.

### Bug 3: Phase E claim sampling too thin

The verifier sampled **5 claims** out of dozens. It happened to catch a
different misuse of s011, but missed:

- TAM cited as `[s001, s002]` in the Conclusion (TAM is s007 = Davis 1989)
- Missing H1/H2/H3 hypothesis structure
- Lit-review "string of `sNNN` quotes" rhetorical pattern

**Fix target:** raise Phase E sample size to `min(30, total_claims)`. Cost
~6× the current claim-verification spend, but Phase E currently
under-samples by an order of magnitude on a 22-source / 60+-claim paper.

### Bug 4: PRISMA-trAIce compliance returns blanket pass

`compliance_check` returned all 10 PRISMA items `not_applicable` with
`block_decision: pass`. PRISMA is for systematic reviews; this paper is a
survey-methodology protocol. The check contributed nothing.

**Fix target:** route compliance check by methodology type. Survey papers
should hit a STROBE / CHERRIES checklist instead of PRISMA. See
`02_research_architect.md` for the methodology hint.

## Infrastructure findings (already partially landed)

### Agent + watchdog timeout coupling

Original: `_AGENT_RUN_TIMEOUT_S = 480.0` (trace_logger.py) / `max_idle_s =
600` (watchdog.py). Tuned for Anthropic LLM proxy SSE wedges. On DeepSeek
official API, `integrity_verification_agent` doing multi-tool Exa work
legitimately needs 500-700s.

**Already fixed:** bumped to 900s agent / 1200s watchdog, keeping the
agent < watchdog invariant. Comment chain in both files now points to
this run.

### PydanticAI ↔ DeepSeek message serialization bug

After thinking-mode turns, PydanticAI emits assistant messages whose
serialized form has neither `content` nor `tool_calls` set. OpenAI accepts
this; DeepSeek rejects with `400 invalid_request_error: "Invalid assistant
message: content or tool_calls must be set"`. Killed run-0511-2107 in the
third pre_integrity round.

**Fix target:** patch `pydantic_ai/models/openai.py` `_map_messages` to
ensure assistant messages always carry a non-empty `content` field (could be
the empty string `""` as a no-op), or write a wrapper that sanitizes
messages before sending to the OpenAI-compat client when
`base_url` indicates a non-OpenAI provider.

### CrossRef rate-limit degradation

The retraction / metadata enrichment checks hit `429 Too Many Requests`
repeatedly on `api.crossref.org`. Non-fatal but reduces the integrity
layer's confidence. CrossRef's "polite pool" lifts rate limits if requests
include `mailto:<email>` in the User-Agent header.

**Fix target:** `src/academic_pipeline/tools/bibliography/doi.py` — set
`User-Agent: "academic-pipeline/2.5.0 (mailto:<email>)"` where the email
comes from `.env` or `authors.yaml`.

## What the run proved positive about

These should NOT be touched — they're working:

- DeepSeek-v4-pro structured-output reliability across 9 distinct
  `PromptedOutput` schemas with zero JSON-parse failures
- `extra_body.thinking.reasoning_effort=max` propagation from YAML
  `model_settings` through `pydantic_ai/models/openai.py:870` to the wire
- Bibliography fabrication risk: 22 sources, 9 DOIs all verified by CrossRef,
  13 non-DOI sources all recognizable real SE/HCI literature
- PYTHONPATH-based editable-install workaround (Python 3.13 + hatchling pth
  underscore-prefix incompatibility)
- Independent verifier producing real verdicts (17 VERIFIED / 2 SUSPICIOUS /
  1 UNVERIFIABLE + 5 substantive red flags), not rubber-stamping

## Topic-suitability heuristic for future runs

The pipeline's current shape requires Results to come from existing data or
literature meta-analysis. Topics that demand novel data collection (surveys,
interviews, RCTs) hit the PENDING-placeholder failure mode every time. Two
fixes possible:

1. (Out of scope) Add a "protocol paper" mode where Results is replaced by
   a Pre-registration section and Discussion shifts to anticipated-finding
   framing.
2. (In scope) Improve `experiment_classifier` to flag novel-data-required
   topics and route them to a brief "switch topic" interactive prompt
   before the writing phase commits.
