"""Deterministic renderers for PaperDraft → markdown and LaTeX.

Pure functions. No LLM calls. Walks the structured PaperDraft model
and produces publication-ready output.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from academic_pipeline.runtime.citation_resolver import (
    resolve_citations_to_cite_commands,
    resolve_citations_to_pandoc,
)


if TYPE_CHECKING:
    from academic_pipeline.models.writing import (
        FigurePackage,
        PaperDraft,
    )

_HEADING_CMDS = {1: r"\section", 2: r"\subsection", 3: r"\subsubsection", 4: r"\paragraph"}

_HEADING_NUMBER_RE = re.compile(r"^\s*(?:Section\s+)?\d+(?:\.\d+)*\.?\s+", re.IGNORECASE)


def _strip_heading_number(heading: str) -> str:
    """Drop a leading ``1.`` / ``2.1`` / ``Section 3.`` prefix from a heading.

    Defensive — primary fix is the section_writer prompt forbidding emission
    of these prefixes, but agents in production may still slip and pandoc's
    --number-sections will double-number anything we let through.

    If stripping would leave an empty string (heading was just a number,
    e.g. "1. " with trailing space), the original heading is returned so
    the malformed input remains visible downstream rather than silently
    becoming `# `.
    """
    stripped = _HEADING_NUMBER_RE.sub("", heading).strip()
    return stripped or heading

_LATEX_ESCAPE_MAP = str.maketrans({
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
})


def render_markdown(
    draft: PaperDraft,
    figure_package: FigurePackage | None = None,
) -> str:
    r"""Render PaperDraft to pandoc-compatible markdown with YAML frontmatter.

    Citations are emitted in pandoc citeproc syntax (``[@bibkey]``). With
    ``--natbib`` + ``acl_natbib.bst`` (the production pandoc configuration),
    these render as parenthetical author-year and pandoc auto-generates the
    references section — no manual list is appended here.

    When ``figure_package`` is provided, ``[FIGURE: N]`` markers in section
    content are replaced with ``![<caption>](figures/figure_NN.png)`` using
    the figure's actual caption as alt-text (so pandoc emits a proper
    ``\caption{...}``). Markers without a matching figure are left in place
    so the gap is visible to the author.
    """
    lines: list[str] = []

    # Build citation key → number mapping (still used by figure tables and
    # external callers; numeric references are no longer baked in here).
    ref_map: dict[str, int] = {}
    for i, ref in enumerate(draft.references, 1):
        ref_map[ref.id] = i

    # YAML frontmatter for pandoc title block
    lines.append("---")
    lines.append(f"title: \"{draft.title}\"")
    if draft.authors:
        author_parts = []
        for a in draft.authors:
            part = a.name
            if a.affiliation:
                part += f", {a.affiliation}"
            author_parts.append(part)
        lines.append(f"author: \"{'; '.join(author_parts)}\"")
    lines.append("abstract: |")
    for abstract_line in draft.abstract.split("\n"):
        lines.append(f"  {abstract_line}")
    lines.append("numbersections: true")
    lines.append("---")
    lines.append("")

    for section in draft.sections:
        if section.heading.lower().strip() in ("abstract",):
            continue
        prefix = "#" * section.level
        lines.append(f"{prefix} {_strip_heading_number(section.heading)}")
        lines.append("")
        content = resolve_citations_to_pandoc(section.content, ref_map)
        content = _convert_inline_math(content)
        if figure_package is not None:
            content = _substitute_figure_markers(content, figure_package)
        lines.append(content)
        lines.append("")

    if figure_package is not None and figure_package.tables:
        lines.append("")
        for table in figure_package.tables:
            if table.headers and table.rows:
                # Headers and cells routed through _convert_inline_math so
                # Unicode operators (×, ≥, ≤, ±) become TeX math envs
                # ($\times$, $\geq$, …). Without this, tabular cells
                # render the Unicode glyphs in Times Roman, which lacks
                # them — producing visible 'Œ' for ×, missing-char boxes
                # for ≥, etc.
                hdr = [_convert_inline_math(h) for h in table.headers]
                lines.append("| " + " | ".join(hdr) + " |")
                lines.append("|" + "|".join(["---"] * len(hdr)) + "|")
                for row in table.rows:
                    row_padded = list(row[: len(hdr)]) + [""] * max(0, len(hdr) - len(row))
                    cells = [_convert_inline_math(c) for c in row_padded]
                    lines.append("| " + " | ".join(cells) + " |")
                # Pandoc-native caption syntax (`: caption-line` directly
                # after a pipe table) renders as \caption{} INSIDE the
                # table env. We deliberately do NOT prefix our own
                # "Table N." — pandoc auto-prepends "Table N: " when it
                # builds the caption, so doing it ourselves duplicates
                # the label ("Table 1: Table 1. Algorithm..." in the
                # historic bug). The visualization_agent's caption
                # strings also embed the same ``Table N\n\nTitle\n\n``
                # APA prefix, which would triple-print the label —
                # _strip_apa_table_prefix removes it.
                caption = table.title
                if table.caption:
                    body = _strip_apa_table_prefix(table.caption, table.title)
                    if body:
                        caption = f"{caption}. {body}"
                # Newlines inside a pandoc caption line break the caption
                # parse, so collapse the multi-paragraph caption to a
                # single line.
                caption = re.sub(r"\s*\n\s*", " ", caption).strip()
                lines.append(f": {caption}")
            else:
                # HONEST cross-reference — NOT fake placeholder rows.
                # When the agent didn't emit row data, surface that
                # explicitly rather than papering over with a fake table.
                placement = table.placement or "the narrative"
                lines.append(
                    f"**Table {table.table_number}.** {table.title} — "
                    f"*detailed values reported in {placement}.*"
                )
            lines.append("")

    # No manual `# References` section: pandoc --natbib generates a
    # hyperlinked, author-year-sorted bibliography from references.bib at
    # the end of the document automatically.

    return "\n".join(lines)


# Order matters. Process scientific-notation p/n/k expressions FIRST so they
# capture the FULL expression in one math env. The shorter `var = digits`
# rule must NOT fire on `p = 7` when the source actually says `p = 7.6e-6`,
# or it leaves `.6e-6` outside math mode (the historic "$p = 7$.6 Œ10ˆ{-6}"
# rendering bug).
_MATH_PATTERNS = [
    # Scientific notation: `p = 7.6e-16`, `p = 7.6E-6`. Capture before the
    # plain-decimal rule fires.
    (
        re.compile(r"(?<!\w)(n|N|p|k)\s*=\s*(-?\d+(?:\.\d+)?)[eE](-?\d+)(?!\w)"),
        r"$\1 = \2 \\times 10^{\3}$",
    ),
    # Scientific notation with explicit `× 10^-N` or `× 10^{-N}` form.
    # Matches `p = 7.6 × 10^-6`, `p = 7.6 \times 10^{-6}`, etc.
    (
        re.compile(
            r"(?<!\w)(n|N|p|k)\s*=\s*(-?\d+(?:\.\d+)?)\s*"
            r"(?:×|\\times|\$?\\times\$?)\s*10\s*\^?\s*\{?(-?\d+)\}?(?!\w)"
        ),
        r"$\1 = \2 \\times 10^{\3}$",
    ),
    # Plain decimal: `p = 7.6`, `n = 25`, `k = 8`. Now safe — anything
    # with scientific notation was caught above.
    (
        re.compile(r"(?<!\w)(n|N|p|k)\s*=\s*(-?\d+(?:\.\d+)?)(?!\w)"),
        r"$\1 = \2$",
    ),
    # Comparison operators with numeric RHS.
    (re.compile(r"(?<!\w)(p)\s*(<|>|<=|>=)\s*(\d+(?:\.\d+)?)"), r"$\1 \2 \3$"),
    # Standalone Unicode operators outside math env: replace with TeX math.
    (re.compile(r"(?<!\$)(≥)(?!\$)"), r"$\\geq$"),
    (re.compile(r"(?<!\$)(≤)(?!\$)"), r"$\\leq$"),
    (re.compile(r"(?<!\$)(≈)(?!\$)"), r"$\\approx$"),
    (re.compile(r"(?<!\$)(→)(?!\$)"), r"$\\rightarrow$"),
    (re.compile(r"(?<!\$)(×)(?!\$)"), r"$\\times$"),
    (re.compile(r"(?<!\$)(±)\s*([\d.]+)"), r"$\\pm \2$"),
    # ASCII fallbacks for `>=` / `<=` typed bare.
    (re.compile(r"(?<![\w$])>=(?![\w$])"), r"$\\geq$"),
    (re.compile(r"(?<![\w$])<=(?![\w$])"), r"$\\leq$"),
]


# Detects the historic broken-math pattern `$X$.Y` where math closes
# immediately before a decimal digit. This is almost always a section
# writer bug (closed `$` too early), and pandoc renders it as visible
# `$` characters in the PDF body. Merge by extending the math env.
_BROKEN_MATH_TAIL = re.compile(r"\$([^$]+?)\$\.(\d+)")


def _convert_inline_math(text: str) -> str:
    """Detect common mathematical patterns and wrap in $...$ for LaTeX.

    Also defensively repairs the `$p = 7$.6` failure mode by extending
    the math environment over the trailing decimal.

    Substitutions only fire on segments OUTSIDE existing ``$...$`` math
    envs — this prevents double-wrapping (``$$p = 0.05$$``) when the
    section writer correctly emitted math from the start.
    """
    # First: defensive repair of the broken-tail pattern. This MUST run
    # before the segment split so closed-too-early math envs get merged.
    while True:
        new_text = _BROKEN_MATH_TAIL.sub(r"$\1.\2$", text)
        if new_text == text:
            break
        text = new_text

    # Apply each pattern to text-mode segments only (segments outside
    # `$...$`). Re-split between patterns: a pattern that wraps text in
    # new `$...$` boundaries must not be matched again by the next
    # pattern (which is how `$$p = 7.6$$ \times 10^{-6}` would happen).
    for pattern, replacement in _MATH_PATTERNS:
        parts = re.split(r"(\$[^$]+\$)", text)
        for i in range(0, len(parts), 2):
            parts[i] = pattern.sub(replacement, parts[i])
        text = "".join(parts)
    return text


_FIGURE_MARKER_RE = re.compile(r"\[FIGURE:\s*(\d+)\]")
# Matches APA-style ("Figure N\n\nTitle") and inline ("Fig. N: Title") prefixes.
# The separator class is `[:.\-—]` OR a newline; the latter covers the
# convention used by the visualization_agent which emits captions as a
# multi-paragraph block (label / title / Note. body).
_LEADING_FIG_LABEL_RE = re.compile(
    r"^\s*(?:Figure|Fig\.?)\s*\d+\s*(?:[:.\-—]\s*|\s*\n+\s*)",
    re.IGNORECASE,
)
# Same APA-form prefix for tables: caption strings start with
# "Table N\n\nTitle\n\nNote. ...".
_LEADING_TABLE_LABEL_RE = re.compile(
    r"^\s*Table\s*\d+(?:\.\d+)?\s*(?:[:.\-—]\s*|\s*\n+\s*)",
    re.IGNORECASE,
)


def _strip_apa_table_prefix(caption: str, title: str) -> str:
    r"""Strip the leading ``Table N\n\nTitle\n\n`` block from a caption.

    The visualization_agent emits captions as
    ``Table N\n\nShort Title\n\nNote. Body text``. Concatenating the
    raw caption after our own ``**Table N.** title`` line would
    duplicate both the label and the title in the rendered PDF (the
    historic ``Table 1: Table 1. Algorithm... Table 1`` failure mode).
    """
    out = _LEADING_TABLE_LABEL_RE.sub("", caption, count=1).lstrip()
    # If the next line is the same as the title, drop it too.
    if title and out.startswith(title):
        out = out[len(title):].lstrip()
    return out


def _substitute_figure_markers(text: str, figure_package: FigurePackage) -> str:
    r"""Replace ``[FIGURE: N]`` markers with markdown image refs.

    The image's alt text is the figure's actual ``caption`` (with any
    leading ``Figure N:`` / ``Fig. N.`` prefix stripped, since pandoc
    auto-prepends its own ``Figure N:`` label). This is the text pandoc
    emits as ``\caption{...}`` — historically this slot was hard-coded to
    ``"Figure N"``, producing nonsense captions like ``Fig. 2. Figure 3``
    in the rendered PDF.

    Path source: prefers ``Figure.source_path``'s basename (a PNG already
    rendered by the experiment-phase Dagster workspace and copied into
    ``build_dir/figures/`` by LatexCompilerNode). Falls back to the legacy
    ``figures/figure_NN.png`` convention for snapshots written before the
    figures-via-dagster pivot. Markers without a matching figure_number
    are left in place so the gap is visible to the author.

    Markdown's ``![alt](path)`` syntax forbids unescaped brackets in alt
    text, so brackets in the caption (e.g. inline citations) are escaped.
    """
    by_num = {fig.figure_number: fig for fig in figure_package.figures}

    def _sub(m: re.Match[str]) -> str:
        n = int(m.group(1))
        fig = by_num.get(n)
        if fig is None:
            return m.group(0)
        if fig.source_path is not None:
            target = f"figures/{fig.source_path.name}"
        else:
            target = f"figures/figure_{n:02d}.png"
        caption = _LEADING_FIG_LABEL_RE.sub("", fig.caption).strip()
        if not caption:
            caption = f"Figure {n}"
        # Escape brackets so markdown image-link parsing isn't broken.
        caption = caption.replace("[", r"\[").replace("]", r"\]")
        return f"![{caption}]({target})"

    return _FIGURE_MARKER_RE.sub(_sub, text)


def render_latex(draft: PaperDraft, bib_source: str = "") -> str:
    """Render PaperDraft to a complete IEEEtran LaTeX document."""
    lines: list[str] = []

    ref_map: dict[str, int] = {ref.id: i for i, ref in enumerate(draft.references, 1)}

    lines.append(r"\documentclass[conference]{IEEEtran}")
    lines.append(r"\usepackage[utf8]{inputenc}")
    lines.append(r"\usepackage[T1]{fontenc}")
    lines.append(r"\usepackage{lmodern}")
    lines.append(r"\usepackage{textcomp}")
    lines.append(r"\usepackage{amsmath,amssymb}")
    lines.append(r"\usepackage{graphicx}")
    lines.append(r"\usepackage{booktabs}")
    lines.append(r"\usepackage{hyperref}")
    lines.append(r"\usepackage{cite}")
    lines.append(r"\usepackage{url}")
    lines.append("")

    lines.append(r"\title{" + _escape_latex(draft.title) + "}")
    lines.append("")

    if draft.authors:
        author_blocks = []
        for a in draft.authors:
            block = r"\IEEEauthorblockN{" + _escape_latex(a.name) + "}"
            if a.affiliation:
                block += "\n" + r"\IEEEauthorblockA{" + _escape_latex(a.affiliation)
                if a.email:
                    block += r" \\ " + _escape_latex(a.email)
                block += "}"
            author_blocks.append(block)
        lines.append(r"\author{" + r" \and ".join(author_blocks) + "}")
    lines.append("")

    lines.append(r"\begin{document}")
    lines.append(r"\maketitle")
    lines.append("")

    lines.append(r"\begin{abstract}")
    lines.append(_md_to_latex(draft.abstract, ref_map))
    lines.append(r"\end{abstract}")
    lines.append("")

    if draft.keywords:
        lines.append(r"\begin{IEEEkeywords}")
        lines.append(", ".join(_escape_latex(k) for k in draft.keywords))
        lines.append(r"\end{IEEEkeywords}")
        lines.append("")

    for section in draft.sections:
        cmd = _HEADING_CMDS.get(section.level, r"\section")
        lines.append(f"{cmd}{{{_escape_latex(_strip_heading_number(section.heading))}}}")
        lines.append("")
        lines.append(_md_to_latex(section.content, ref_map))
        lines.append("")

    if bib_source:
        lines.append(r"\bibliographystyle{IEEEtran}")
        lines.append(r"\bibliography{references}")
    elif draft.references:
        lines.append(r"\begin{thebibliography}{99}")
        for ref in draft.references:
            label = _escape_latex(ref.id)
            citation = _escape_latex(ref.full_citation)
            lines.append(f"\\bibitem{{{label}}} {citation}")
        lines.append(r"\end{thebibliography}")

    lines.append("")
    lines.append(r"\end{document}")
    lines.append("")

    return "\n".join(lines)


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters and Unicode in plain text."""
    text = text.translate(_LATEX_ESCAPE_MAP)
    text = text.replace("—", "---")
    text = text.replace("–", "--")
    text = text.replace("‘", "`")
    text = text.replace("’", "'")
    text = text.replace("“", "``")
    text = text.replace("”", "''")
    text = text.replace("…", "...")
    text = text.replace(" ", "~")
    text = text.replace("→", r"$\rightarrow$")
    text = text.replace("←", r"$\leftarrow$")
    text = text.replace("≥", r"$\geq$")
    text = text.replace("≤", r"$\leq$")
    text = text.replace("≈", r"$\approx$")
    text = text.replace("×", r"$\times$")
    text = text.replace("±", r"$\pm$")
    text = text.replace("∼", r"$\sim$")
    text = text.replace("•", r"\textbullet{}")
    text = re.sub(r"[^\x00-\x7F]", lambda m: _unicode_to_latex(m.group()), text)
    return text


def _unicode_to_latex(char: str) -> str:
    """Convert a single Unicode character to its LaTeX equivalent."""
    _map = {
        "á": r"\'a", "à": r"\`a", "â": r"\^a", "ä": r'\"a', "å": r"\aa{}",
        "é": r"\'e", "è": r"\`e", "ê": r"\^e", "ë": r'\"e',
        "í": r"\'i", "ì": r"\`i", "î": r"\^i", "ï": r'\"i',
        "ó": r"\'o", "ò": r"\`o", "ô": r"\^o", "ö": r'\"o',
        "ú": r"\'u", "ù": r"\`u", "û": r"\^u", "ü": r'\"u',
        "ñ": r"\~n", "ç": r"\c{c}", "ć": r"\'c", "č": r"\v{c}",
        "š": r"\v{s}", "ž": r"\v{z}", "ř": r"\v{r}",
        "Á": r"\'A", "É": r"\'E", "Í": r"\'I", "Ó": r"\'O", "Ú": r"\'U",
        "Ä": r'\"A', "Ö": r'\"O', "Ü": r'\"U', "Ñ": r"\~N",
        "ß": r"\ss{}", "æ": r"\ae{}", "ø": r"\o{}", "Ø": r"\O{}",
    }
    return _map.get(char, "")


def _convert_citations(text: str, ref_map: dict[str, int]) -> str:
    r"""Bibliography-aware: convert ``[bibkey]`` to ``\cite{bibkey}`` for known keys.

    REQUIRES ref_map — there is no fallback to regex matching. Callers
    without a bibliography must construct an empty dict explicitly.
    """
    return resolve_citations_to_cite_commands(text, ref_map)


_CITE_SENTINEL_PREFIX = "ZZCITEPROTECTZZ"
_CITE_SENTINEL_SUFFIX = "ZZENDZZ"


def _md_to_latex(text: str, ref_map: dict[str, int]) -> str:
    r"""Convert markdown patterns in section content to LaTeX.

    Token-protects \cite commands BEFORE _escape_latex so backslashes,
    underscores, and braces inside cite keys are never escaped. Uses
    PRINTABLE alphanumeric sentinels (no null bytes, no LaTeX-special
    chars) to avoid breaking pandoc/log/JSON or being mangled by
    _escape_latex's underscore/brace replacements.
    """
    if _CITE_SENTINEL_PREFIX in text:
        raise RuntimeError(
            f"Source text contains the cite-protection sentinel prefix "
            f"{_CITE_SENTINEL_PREFIX!r}; would corrupt rendering. "
            f"This should never happen in real paper text."
        )

    text = _convert_citations(text, ref_map)

    placeholders: dict[str, str] = {}

    def _stash(m: re.Match[str]) -> str:
        idx = len(placeholders)
        token = f"{_CITE_SENTINEL_PREFIX}{idx:04d}{_CITE_SENTINEL_SUFFIX}"
        placeholders[token] = m.group(0)
        return token

    text = re.sub(r"\\cite\{[^}]+\}", _stash, text)
    text = _escape_latex(text)
    for token, original in placeholders.items():
        text = text.replace(token, original)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"__(.+?)__", r"\\textbf{\1}", text)

    # Italic: *text* or _text_ (but not inside \textbf)
    text = re.sub(r"(?<!\*)\\?\*(.+?)\\?\*(?!\*)", r"\\textit{\1}", text)

    # Inline code: `text`
    text = re.sub(r"`([^`]+)`", r"\\texttt{\1}", text)

    # Unordered lists: lines starting with - or *
    text = _convert_lists(text, unordered=True)

    # Ordered lists: lines starting with 1. 2. etc.
    text = _convert_lists(text, unordered=False)

    # Blockquotes: lines starting with >
    text = _convert_blockquotes(text)

    return text


def _convert_lists(text: str, *, unordered: bool) -> str:
    """Convert markdown lists to LaTeX itemize/enumerate."""
    if unordered:
        pattern = re.compile(r"^[\-\*]\s+", re.MULTILINE)
        env = "itemize"
    else:
        pattern = re.compile(r"^\d+\.\s+", re.MULTILINE)
        env = "enumerate"

    if not pattern.search(text):
        return text

    result_lines: list[str] = []
    in_list = False
    for line in text.split("\n"):
        match = pattern.match(line)
        if match:
            if not in_list:
                result_lines.append(f"\\begin{{{env}}}")
                in_list = True
            item_text = line[match.end():]
            result_lines.append(f"  \\item {item_text}")
        else:
            if in_list:
                result_lines.append(f"\\end{{{env}}}")
                in_list = False
            result_lines.append(line)
    if in_list:
        result_lines.append(f"\\end{{{env}}}")

    return "\n".join(result_lines)


def _convert_blockquotes(text: str) -> str:
    """Convert markdown blockquotes to LaTeX quote environment."""
    if not re.search(r"^>\s", text, re.MULTILINE):
        return text

    result_lines: list[str] = []
    in_quote = False
    for line in text.split("\n"):
        if line.startswith("> "):
            if not in_quote:
                result_lines.append(r"\begin{quote}")
                in_quote = True
            result_lines.append(line[2:])
        else:
            if in_quote:
                result_lines.append(r"\end{quote}")
                in_quote = False
            result_lines.append(line)
    if in_quote:
        result_lines.append(r"\end{quote}")

    return "\n".join(result_lines)
