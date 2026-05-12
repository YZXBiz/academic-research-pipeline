"""Bibliography-aware citation resolution.

A `[token]` is a citation iff `token` is a key in the bibliography. This
eliminates the false-positive surface of pure-regex matchers
([NCT...], [CVE-...], [1], [IV] etc.) without heuristic guessing.

Adjacent known citations like [a][b] or [a] [b] are merged into [a,b].
Adjacency merging only happens when BOTH keys are known — mixing known
with unknown leaves both alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable


# Bracket tokens that MIGHT be cite keys. Whether they actually are
# is decided by ref_map lookup, not by token shape. Internal whitespace
# (e.g. ``[smith2020, doe2021]``) is allowed; ``.strip()`` handles it.
# Year-bearing filtering is applied only in ``extract_cite_tokens``,
# which serves a different role (heuristic discovery for downstream
# tooling).
_TOKEN_PATTERN = re.compile(r"\[([^\[\]]+?)\]")
_HAS_YEAR = re.compile(r"\d{4}")


def extract_cite_tokens(text: str) -> list[str]:
    """Return all bracket tokens that could be citation keys (year-bearing only)."""
    out: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text):
        for sub in match.group(1).split(","):
            sub = sub.strip()
            if sub and _HAS_YEAR.search(sub):
                out.append(sub)
    return out


def _is_known_group(group: str, ref_map: dict[str, int]) -> bool:
    """A comma-separated group is 'known' iff every key in it is in ref_map."""
    return all(k.strip() in ref_map for k in group.split(","))


def _resolve(text: str, ref_map: dict[str, int], formatter: Callable[[list[str]], str]) -> str:
    """Walk bracket tokens, formatting only those entirely composed of known keys."""
    # Merge adjacent groups where ALL keys (across both groups) are known
    while True:
        merged = re.sub(
            r"\[([^\[\]]+)\]\s*\[([^\[\]]+)\]",
            lambda m: (
                f"[{m.group(1)},{m.group(2)}]"
                if _is_known_group(m.group(1), ref_map) and _is_known_group(m.group(2), ref_map)
                else m.group(0)
            ),
            text,
            count=1,
        )
        if merged == text:
            break
        text = merged

    def _fmt(m: re.Match[str]) -> str:
        body = m.group(1)
        if not _is_known_group(body, ref_map):
            return m.group(0)
        return formatter([k.strip() for k in body.split(",")])

    return _TOKEN_PATTERN.sub(_fmt, text)


def resolve_citations_to_cite_commands(text: str, ref_map: dict[str, int]) -> str:
    r"""Convert ``[bibkey]`` to ``\cite{bibkey}`` for keys present in ref_map."""
    return _resolve(text, ref_map, lambda keys: r"\cite{" + ",".join(keys) + "}")


def resolve_citations_to_numbers(text: str, ref_map: dict[str, int]) -> str:
    """Convert ``[bibkey]`` to ``[N]`` numbered references for keys in ref_map."""
    def _fmt(keys: list[str]) -> str:
        nums = [str(ref_map[k]) for k in keys]
        return "[" + ", ".join(nums) + "]"
    return _resolve(text, ref_map, _fmt)


def resolve_citations_to_pandoc(text: str, ref_map: dict[str, int]) -> str:
    """Convert ``[bibkey]`` to ``[@bibkey]`` pandoc citeproc syntax.

    Multi-key groups become ``[@a; @b]`` (semicolon-separated, the pandoc
    convention). Only keys present in ``ref_map`` are rewritten — unknown
    bracket tokens like ``[1]`` or ``[NCT12345]`` are left alone.

    With ``--natbib`` (or ``--citeproc``), pandoc renders ``[@key]`` as
    parenthetical author-year (e.g. ``(Smith et al., 2023)``) and
    automatically generates a hyperlinked references list at the end of
    the document.
    """
    def _fmt(keys: list[str]) -> str:
        return "[" + "; ".join(f"@{k}" for k in keys) + "]"
    return _resolve(text, ref_map, _fmt)
