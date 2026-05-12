# MD Quality Rubric

Reference for the MD quality auditor subagent.

## Quality Scoring (1-10)

| Score | Description |
|-------|-------------|
| 9-10 | PhD-grade. Original synthesis, novel framing, statistical rigor, deep domain integration. |
| 7-8 | Solid review-quality. Clear structure, accurate citations, but limited novelty. |
| 5-6 | Adequate. Covers basics but reads as a summary, not a contribution. |
| 3-4 | Shallow. Generic claims, weak citations, missing depth. |
| 1-2 | Broken. Placeholders, hallucinations, incoherent. |

## Per-Node Quality Checks

### research_question.md
- Has explicit research question (not topic restatement)
- 2-4 sub-questions decomposing the main RQ
- FINER scores present (feasible/interesting/novel/ethical/relevant)
- Scope section with in_scope, out_of_scope, domain, timeframe, geography, population
- Methodology type specified

### research_architect.md
- Methodology blueprint with concrete steps
- Data sources identified (real datasets, not "could use X")
- Analysis plan specified
- Limitations acknowledged

### bibliography.md
- 15+ references minimum
- DOIs or stable identifiers
- Recent papers (2018-2025 mostly)
- Mix of seminal + recent
- No fabricated citations (cross-check titles look real)

### synthesis.md
- Goes beyond bibliography summary
- Identifies tensions, gaps, agreements across literature
- Domain-theoretic framing (not just "X researchers found Y")
- Sets up the contribution this paper will make

### experiment_plan.md (if --force-experiment)
- Concrete dataset(s) with source URLs
- Specific methods (e.g., "XGBoost vs LogReg vs AutoGluon")
- Statistical tests planned
- Baselines defined
- Success criteria measurable

### experiment_results.json + analysis.md
- Real metrics (not placeholders)
- Multiple seeds reported
- CIs or std reported
- Figures generated
- Analysis goes beyond "method X scored Y" — explains WHY

### paper outline / drafts
- Standard sections (intro, methods, results, discussion, conclusion)
- Word counts realistic for an academic paper (8000+ total)
- Section transitions coherent
- Claims backed by evidence from synthesis or experiments

### review reports
- Specific actionable feedback
- Severity tags (critical/major/minor)
- Cites specific sections of the paper

## Plan Adherence Checks

The pipeline runs these stages in order:
1. **Intake** — initialize state
2. **Research** — RQ → Architect → Bibliography → Synthesis → KnowledgeGraph → CrossModelVerification → Ethics → EICReview
3. **Experiment classifier** — decides if experiment phase runs
4. **Experiment** (if needed) — Design → InteractiveML ⇄ Judge → Analysis
5. **Writing** — Intake → Outline → Argument → Sections → Style
6. **PreIntegrity** — claims/plagiarism check
7. **Review** — multi-reviewer
8. **FinalIntegrity** — final compliance check
9. **Finalize** — render paper.md, paper.tex, paper.pdf

If you see artifacts appearing OUT OF ORDER (e.g., paper.md appearing before synthesis.md), flag as plan violation.

If you see MISSING artifacts (e.g., experiment phase ran but no experiment_results.json), flag as broken.

## Critical Red Flags (escalate immediately)

- "TODO" or "TBD" or "[placeholder]" in any final artifact
- Citations like "Author et al. (year)" without real names/years
- DOIs that don't follow `10.xxxx/yyyy` pattern
- Section content that's < 100 words when the rubric expects 500+
- Fabricated dataset URLs (must be sklearn / huggingface / ucimlrepo / known repos)
- Reviewer reports that just say "looks good" with no specifics
- Metrics that look implausible (AUC = 1.0, accuracy = 100%)

## Reference: Depth Gaps Feedback

Per project memory, papers from this pipeline have historically suffered from:
- Reading as lit reviews instead of original research
- Missing data and modeling depth
- Weak domain-theoretic integration

Specifically watch synthesis and analysis files for these patterns. Flag if you see them.
