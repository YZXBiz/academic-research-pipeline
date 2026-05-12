"""Async LaTeX compiler tool wrapping tectonic.

Writes .tex and .bib files, shells out to tectonic for compilation,
and returns the path to the resulting PDF.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from academic_pipeline.models.numerical import NumericalStore
    from academic_pipeline.runtime.events import EventLogger


logger = logging.getLogger(__name__)

# Vendored ACL conference style files + lua filter, copied per build into the
# tectonic working directory so \usepackage{acl}, \bibliographystyle{acl_natbib},
# and the longtable→table* rewriter resolve from cwd.
_PANDOC_TEMPLATES_DIR = Path(__file__).resolve().parents[3].parent / "templates" / "pandoc"
_ACL_STYLE_DIR = _PANDOC_TEMPLATES_DIR / "acl"
_ACL_HEADER = _PANDOC_TEMPLATES_DIR / "acl-header.tex"
_LONGTABLE_FILTER = _PANDOC_TEMPLATES_DIR / "longtable-to-table-star.lua"


def _copy_acl_assets(build_dir: Path) -> None:
    r"""Copy acl.sty, acl_natbib.bst, header, and lua filter into build_dir.

    Tectonic looks for \usepackage{acl} and \bibliographystyle{acl_natbib}
    in the working directory; pandoc resolves --include-in-header and
    --lua-filter relative to its cwd. Copying everything into the per-build
    tempdir keeps the compile hermetic.
    """
    for src in (
        _ACL_STYLE_DIR / "acl.sty",
        _ACL_STYLE_DIR / "acl_natbib.bst",
        _ACL_HEADER,
        _LONGTABLE_FILTER,
    ):
        if not src.exists():
            raise FileNotFoundError(
                f"required pandoc asset missing: {src}. "
                f"Re-vendor from https://github.com/acl-org/acl-style-files "
                f"(see templates/pandoc/acl/README.md)."
            )
        shutil.copy(src, build_dir / src.name)


def apply_traceability_substitutions(
    manuscript_text: str,
    store: NumericalStore,
    traceability_mode: str,
    experiment_runs: list[Any],
) -> str:
    r"""Apply traceability substitutions + appendices to manuscript LaTeX/markdown.

    No-op when ``traceability_mode == "off"``. When ``"partial"`` or ``"full"``:
      - replaces ``⟨num:label⟩`` tokens with ``\hyperlink{num_<label>}{value}``
      - appends Notes appendix listing cited numerical products
    When ``"full"`` additionally:
      - appends Code appendix with ``\hypertarget`` at producing code lines

    Args:
        manuscript_text: the rendered manuscript text BEFORE pandoc.
        store: the per-run NumericalStore (typically state.numerical_store).
        traceability_mode: ``"off"`` | ``"partial"`` | ``"full"``.
        experiment_runs: iterable of run-shaped objects (see code_appendix.py).
                         May be empty for runs without experiments.

    Returns:
        Manuscript text with substitutions applied and appendices appended,
        or the original text unchanged when mode == ``"off"``.
    """
    if traceability_mode == "off":
        return manuscript_text

    import re

    from academic_pipeline.traceability._patterns import NUM_TOKEN_PATTERN
    from academic_pipeline.traceability.notes_appendix import generate_notes_appendix
    from academic_pipeline.traceability.substitution import substitute_tokens

    # Collect cited labels from the manuscript (regex matches the same NUM_TOKEN_PATTERN
    # used by the validator and substitution renderer)
    cited = set(re.findall(NUM_TOKEN_PATTERN, manuscript_text))

    # Substitute tokens with hyperlinks (raises SubstitutionFailure on unresolved)
    substituted = substitute_tokens(manuscript_text, store, output_format="latex")

    # Append Notes appendix only if any tokens were cited
    appendix = generate_notes_appendix(store, cited)
    if appendix:
        substituted = substituted + "\n\n" + appendix

    if traceability_mode == "full" and experiment_runs:
        from academic_pipeline.traceability.code_appendix import generate_code_appendix

        code_section = generate_code_appendix(experiment_runs)
        if code_section:
            substituted = substituted + "\n\n" + code_section

    return substituted


def write_latex_files(tex_source: str, bib_source: str, output_dir: Path) -> None:
    """Write paper.tex and optionally references.bib to output_dir.

    Creates output_dir if it does not exist. Skips writing .bib when bib_source is empty.

    Args:
        tex_source: LaTeX document source.
        bib_source: BibTeX bibliography source (empty string to skip).
        output_dir: Directory to write files into.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "paper.tex").write_text(tex_source, encoding="utf-8")
    if bib_source:
        (output_dir / "references.bib").write_text(bib_source, encoding="utf-8")


async def _run_tectonic(working_dir: Path) -> tuple[int, str]:
    """Shell out to ``tectonic paper.tex`` in *working_dir*.

    Returns:
        Tuple of (return_code, combined_output) where combined_output: contains both stdout and stderr.
    """
    proc = await asyncio.create_subprocess_exec(
        "tectonic",
        "paper.tex",
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace")


async def _run_doi_build_gate(
    bib_source: str,
    *,
    allow_unverified_dois: bool,
    event_logger: EventLogger | None,
) -> None:
    """§6.7.T2 build gate: verify every DOI in *bib_source* via CrossRef.

    Raises ``DOICrossRefError`` (REN001) on any unverified DOI when
    ``allow_unverified_dois`` is ``False``. When ``True``, logs + still
    emits one ``doi_gate_failure`` event per failure (with ``blocking=False``)
    so the operator decision is recorded, but allows the build to proceed.

    No-ops when *bib_source* is empty.
    """
    if not bib_source:
        return

    from academic_pipeline.runtime.rendering_errors import DOICrossRefError
    from academic_pipeline.tools.bibliography.doi import verify_dois_in_bibtex

    results = await verify_dois_in_bibtex(bib_source)
    failures = [r for r in results if not r["verified"]]
    if not failures:
        return

    if event_logger is not None:
        for r in failures:
            event_logger.emit_sync(
                "doi_gate_failure",
                doi=str(r["doi"]),
                crossref_status=int(r["crossref_status"]),  # type: ignore[arg-type]
                blocking=not allow_unverified_dois,
                error_code="REN001",
            )

    if allow_unverified_dois:
        logger.warning(
            "DOI gate: %d unverified DOI(s) bypassed via allow_unverified_dois",
            len(failures),
        )
        return

    raise DOICrossRefError(unverified_dois=[str(r["doi"]) for r in failures])


async def compile_pdf_pandoc(
    markdown: str,
    bib_source: str,
    output_dir: Path,
    numerical_store: NumericalStore | None = None,
    traceability_mode: str = "off",
    experiment_runs: list[Any] | None = None,
    *,
    allow_unverified_dois: bool = False,
    event_logger: EventLogger | None = None,
) -> Path | None:
    r"""Compile markdown to *ACL conference PDF via pandoc.

    Uses pandoc's default LaTeX template + ACL style file (vendored at
    ``templates/pandoc/acl/``) to produce a 2-column, A4, Times-set paper
    that matches the ACL/NAACL house format.

    Bibliography is processed via natbib using the vendored ``acl_natbib.bst``
    style — citation calls in the markdown should be in pandoc citeproc
    syntax (``[@bibkey]``, ``[@a; @b]``) and the resolved authors-and-year
    references list is appended automatically by pandoc.

    Tables wider than a single column are spanned by the
    ``longtable-to-table-star.lua`` filter, which rewrites pandoc's default
    ``longtable`` (illegal in 2-column mode) to ``\begin{table*}``.

    When ``numerical_store`` is provided and ``traceability_mode`` is not ``"off"``,
    substitutes ⟨num:label⟩ tokens and appends Notes/Code appendices before pandoc
    is invoked. Defaults preserve the previous behavior (no traceability layer).
    """
    # §6.7.T2 — DOI CrossRef build gate. Runs BEFORE any disk writes or
    # pandoc invocation so a failed gate aborts cleanly with no partial
    # artifacts. Raises DOICrossRefError (REN001) on unverified DOIs in
    # the default fail-closed mode.
    await _run_doi_build_gate(
        bib_source,
        allow_unverified_dois=allow_unverified_dois,
        event_logger=event_logger,
    )

    if numerical_store is not None:
        markdown = apply_traceability_substitutions(
            markdown,
            numerical_store,
            traceability_mode,
            experiment_runs or [],
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "paper.md").write_text(markdown, encoding="utf-8")
    if bib_source:
        (output_dir / "references.bib").write_text(bib_source, encoding="utf-8")

    _copy_acl_assets(output_dir)

    cmd = [
        "pandoc",
        "paper.md",
        "-o",
        "paper.pdf",
        "--pdf-engine=tectonic",
        # Standard article class + 11pt is what acl.sty expects.
        "-V",
        "documentclass=article",
        "-V",
        "classoption=11pt",
        # Numbered sections (1, 2, 2.1) — ACL style.
        "--number-sections",
        # acl.sty + Times font + table/figure caption styling.
        "--include-in-header=acl-header.tex",
        # Promote markdown tables to table* so they span both columns
        # (longtable refuses to compile under 2-column).
        "--lua-filter=longtable-to-table-star.lua",
    ]

    # natbib bibliography only when we actually have a .bib file. Without
    # this guard pandoc would emit \bibliography{references} that tectonic
    # would fail on. We deliberately omit --biblatex / -V biblio-style:
    # acl.sty already calls \bibliographystyle{acl_natbib} internally
    # (acl.sty:195) and a second \bibstyle would crash bibtex with
    # "Illegal, another \bibstyle command".
    if bib_source:
        cmd += [
            "--natbib",
            "--bibliography=references.bib",
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        logger.warning("pandoc failed (exit %d):\n%s", proc.returncode, output)
        return None

    pdf_path = output_dir / "paper.pdf"
    if not pdf_path.exists():
        logger.warning("pandoc exited 0 but paper.pdf not found in %s", output_dir)
        return None
    return pdf_path


async def compile_latex(tex_source: str, bib_source: str, output_dir: Path) -> Path | None:
    """Compile LaTeX source to PDF via tectonic.

    Writes source files, runs tectonic, and returns the path to the resulting PDF on success or ``None`` on failure.

    Args:
        tex_source: LaTeX document source.
        bib_source: BibTeX bibliography source (empty string to skip).
        output_dir: Directory for source files and build output.

    Returns:
        Path to ``paper.pdf`` if compilation succeeds, otherwise ``None``.
    """
    write_latex_files(tex_source, bib_source, output_dir)
    return_code, output = await _run_tectonic(output_dir)
    if return_code != 0:
        logger.warning("tectonic failed (exit %d):\n%s", return_code, output)
        return None
    pdf_path = output_dir / "paper.pdf"
    if not pdf_path.exists():
        logger.warning("tectonic exited 0 but paper.pdf not found in %s", output_dir)
        return None
    return pdf_path
