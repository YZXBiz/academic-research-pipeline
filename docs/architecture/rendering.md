# Rendering Pipeline

How a `PaperDraft` becomes a journal-format PDF: figures-via-Dagster, three
template targets, four build-time gates, and a Lua filter for the longtable
problem. Each section is a single mechanism the v2.5.0 build relies on; the
full path runs through `src/academic_pipeline/runtime/paper_renderer.py` →
`src/academic_pipeline/runtime/citation_resolver.py` →
`src/academic_pipeline/tools/rendering/latex_compiler.py` → pandoc + tectonic.

PRD anchor: §6.7 (Rendering).

## Figures-via-Dagster (no in-graph re-execution)

Figures are produced by the experiment subgraph's Dagster `@asset` modules
(generated per-experiment by `config_writer`) and saved under
`02-experiment/figures/<basename>.{pdf,png}`. The writing graph then **copies**
those pre-rendered images into pandoc's per-build tempdir at
`<build_dir>/figures/` rather than re-executing matplotlib code.

`LatexCompilerNode.run` (writing/graph.py) walks `state.figure_package.figures`
and `shutil.copy(spec.source_path, build_dir / "figures" / spec.source_path.name)`
for every `Figure` whose `source_path` exists. Markers in the manuscript
(`[FIGURE: N]`) are rewritten by `runtime/paper_renderer.py::_substitute_figure_markers`
to `![<caption>](figures/<basename>)`; markers WITHOUT a matching figure are
**LEFT IN PLACE** so the gap is visible to the author (NOT silent-skipped —
explicit anti-pattern from the v2.4.0 sandbox-runner days).

`_substitute_figure_markers` uses `source_path.name` verbatim — extension
agnostic — so the publication-style helper's `.pdf` outputs (§6.7.T5) and
the legacy `.png` outputs both work without code change.

## Template selection

Three template targets, all running through `compile_pdf_pandoc` in
`tools/rendering/latex_compiler.py`:

| Target | Class | Layout | When |
|---|---|---|---|
| `acl` (default) | `\documentclass{article}` + `acl.sty` | 2-column A4, Times | ACL/NAACL submissions |
| `ieee` | `IEEEtran[journal,onecolumn]` | 1-column journal | Single-column manuscripts (`longtable` cannot compile under 2-column) |
| `journal+onecolumn` | (alias for `ieee`, kept for back-compat) | 1-column | Same as above |

The ACL path is production: `_copy_acl_assets(build_dir)` copies
`templates/pandoc/acl/{acl.sty,acl_natbib.bst,README.md}` +
`templates/pandoc/acl-header.tex` + `templates/pandoc/longtable-to-table-star.lua`
into the pandoc tempdir per build (pandoc resolves `--include-in-header` and
`--lua-filter` relative to its cwd). The exact pandoc invocation:

```bash
pandoc paper.md -o paper.pdf \
  --pdf-engine=tectonic \
  -V documentclass=article -V classoption=11pt \
  --number-sections \
  --include-in-header=acl-header.tex \
  --lua-filter=longtable-to-table-star.lua \
  [--natbib --bibliography=references.bib]   # only when bib_source truthy
```

The `--natbib` + `--bibliography` flags are conditional: omitting them when
`bib_source == ""` prevents pandoc from emitting `\bibliography{references}`
that tectonic would then fail on (no `.bib` file present).

### CRITICAL anti-pattern (PRD AP60)

**NEVER add `--biblatex` or `-V biblio-style` to the pandoc invocation.**
`acl.sty:195` already calls `\bibliographystyle{acl_natbib}` internally; a
second `\bibstyle` crashes bibtex with `"Illegal, another \bibstyle command"`.
Anything that looks like a "missing flag" would silently break every ACL
build. The conditional bib flags above are the only `--natbib` related
arguments allowed.

## DOI CrossRef build gate (REN001)

Per PRD §6.7.T2 + R17. Default fail-closed.

`_run_doi_build_gate(bib_source, allow_unverified_dois, event_logger)` runs
BEFORE any disk write or pandoc spawn so a failed gate aborts cleanly with
no partial artifacts. Steps:

1. `verify_dois_in_bibtex(bib_source)` extracts every DOI-bearing entry
   (placeholder values `None`/`null`/`n/a` are skipped) and runs
   `verify_doi(doi)` against doi.org in parallel via `asyncio.gather`.
2. Failures (HTTP non-2xx, network errors) are collected.
3. Per AP37, every failure emits one `doi_gate_failure` event via the
   supplied `EventLogger` carrying `{doi, crossref_status, blocking,
   error_code: "REN001"}`. `blocking=False` only when the operator passed
   the escape hatch.
4. If any failures AND `allow_unverified_dois=False` (default), raise
   `DOICrossRefError(unverified_dois=[...])` (REN001) so the build aborts.
5. Operator escape hatch: `compile_pdf_pandoc(..., allow_unverified_dois=True)`
   (CLI flag `--allow-unverified-dois` per OQ7) bypasses the abort but
   still emits the events with `blocking=False` so the decision is recorded.

Sources: `runtime/rendering_errors.py::DOICrossRefError`,
`tools/bibliography/doi.py::verify_dois_in_bibtex`,
`tools/rendering/latex_compiler.py::_run_doi_build_gate`.

## authors.yaml gate (REN002)

Per PRD §6.7.T3. `LatexCompilerNode.run` calls
`resolve_authors_yaml_path(Path.cwd())` then `load_authors_yaml(path)` at
the top of the node, BEFORE pandoc. Missing file or schema-invalid file
aborts with `AuthorsYamlMissingError(searched_paths=[...], reason=...)`
(REN002).

### Schema (per OQ13)

Two file shapes accepted at load time:

```yaml
# Top-level list:
- name: Jane Doe          # required
  affiliation: Some Lab   # default ""
  email: jane@lab.org     # optional
  orcid: 0000-0001-...    # optional

# OR nested under authors: key:
authors:
  - name: ...
    affiliation: ...
```

Both round-trip to `list[AuthorsYamlEntry]`. The Pydantic model is frozen
with `extra="forbid"` so unknown keys raise REN002 with a clear schema
message. Empty list → REN002 (operator can't ship an authors-less paper).

Sources: `runtime/authors_yaml.py::AuthorsYamlEntry`, `load_authors_yaml`,
`resolve_authors_yaml_path`.

## Title 12-word constraint (REN003)

Per PRD §6.7.T4. The `formatter` agent's `output_validator`
`validate_formatter_title(output: FormattedPaper)` reads
`output.metadata["title"]`; raises `ModelRetry` carrying the REN003 marker
when `len(title.split()) > 12`. PydanticAI then re-prompts the model
exactly once (`output_retries: 1` in `formatter.yaml` per "one revision
attempt allowed"); the second consecutive failure escalates `ModelRetry`
to `UnexpectedModelBehavior` and the writing graph aborts.

Edge cases: missing/empty `title` metadata passes through (some runs leave
the title to the rendering layer); exactly 12 words pass; 13 words fail.

Sources: `writing/agents.py::validate_formatter_title`,
`runtime/rendering_errors.py::TitleTooLongError` (REN003, MAX_WORDS=12),
`writing/specs/formatter.yaml::output_retries: 1`.

## longtable → table* Lua filter

ACL templates (and any 2-column LaTeX class) **cannot** compile a markdown
table that pandoc emits as `\begin{longtable}` — longtable is single-column
only. `templates/pandoc/longtable-to-table-star.lua` rewrites the AST so
pandoc emits `\begin{table*}` instead, which spans both columns.

The filter is auto-attached via `--lua-filter=longtable-to-table-star.lua`
in the pandoc invocation. It's copied into the per-build tempdir by
`_copy_acl_assets` so pandoc's relative-path resolution works.

Test coverage: `tests/unit/tools/test_lua_filter_longtable_rewrite.py`.

## Citation styles

`tools/bibliography/citations.py::_FORMATTERS` handles 6 styles via
`format_citation(meta, style="...")`:

| Style | Function | In-text format |
|---|---|---|
| `APA7` | `_format_apa7` | (Author, Year) |
| `Chicago` | `_format_chicago` | (Author Year) |
| `MLA` | `_format_mla` | (Author Page) |
| `IEEE` | `_format_ieee` | [N] |
| `Vancouver` | `_format_vancouver` | (N) |
| `ACL` | `_format_acl` | (Author Year) |

`convert_citation_style(text, from_style, to_style)` round-trips via the
intermediate `CitationMetadata` representation. `validate_citation` enforces
per-style required fields.

ACL anthology format (§6.7.T9) emits full author names with `and` joiner,
year on its own with period, italicized journal/proceedings, and colon-notated
pages (e.g. `5(2):100-115`). Inproceedings entries use `In *Proceedings...*,
pages X-Y.`. ACL-template renders also use natbib via `acl_natbib.bst` for the
LaTeX bibliography path; the `_format_acl` formatter is for plain-text
references where structured BibTeX isn't appropriate.

## Traceability tokens at compile time

Independent of the four gates above. Per PRD §6.10 + §6.7's
`apply_traceability_substitutions` step in `compile_pdf_pandoc`:

When `numerical_store` is supplied AND `traceability_mode != "off"`,
`⟨num:label⟩` tokens (Unicode angle brackets U+27E8/U+27E9) are substituted
to `\hyperlink{num_<label>}{value}` and the Notes appendix is appended to
the manuscript. With `traceability_mode == "full"` the Code appendix is
also appended. See `docs/architecture/traceability.md` for the full chain.

Substitution runs **before** pandoc so the appendices flow through pandoc's
normal markdown→LaTeX path.

## Test coverage

| Test file | Surface |
|---|---|
| `tests/unit/runtime/test_paper_renderer.py` | Markdown + LaTeX renderers, figure-marker substitution |
| `tests/unit/runtime/test_citation_resolver_pandoc.py` | `[bibkey]` → `[@bibkey]` rewrite |
| `tests/unit/runtime/test_paper_renderer_captions.py` | Caption text + numbering |
| `tests/unit/runtime/test_paper_renderer_source_path.py` | Figure path round-trip |
| `tests/unit/tools/test_latex_compiler.py` | tectonic invocation paths |
| `tests/unit/tools/test_doi_build_gate.py` | §6.7.T2 REN001 |
| `tests/unit/runtime/test_authors_yaml.py` | §6.7.T3 REN002 (loader) |
| `tests/unit/writing/test_latex_compiler_authors_gate.py` | §6.7.T3 REN002 (gate) |
| `tests/unit/writing/test_formatter_title_gate.py` | §6.7.T4 REN003 |
| `tests/unit/templates/test_publication_style.py` | §6.7.T5 PUB_STYLE rcParams |
| `tests/unit/tools/test_lua_filter_longtable_rewrite.py` | longtable filter |
| `tests/unit/tools/test_citations.py` | STYLE_DISPATCH (when added) |
| `tests/integration/test_pipeline_graph.py::TestACLBuildSmoke` | §6.7.T6 ACL e2e (medium-marked) |

## Cross-reference

- `docs/architecture/traceability.md` — `⟨num:label⟩` token chain that flows
  through this pipeline before pandoc.
- `docs/architecture/observability.md` — how the `doi_gate_failure` event
  also lands in Logfire.
- PRD §6.7 — full delta + verification block.
- PRD §17 — REN namespace error code table (REN001-REN006).
- PRD §28 AP60 — the do-not-add-`--biblatex` anti-pattern in detail.
