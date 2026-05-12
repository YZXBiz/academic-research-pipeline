"""Rendering-namespace errors per PRD section 17 (REN000-REN099).

REN001 - DOICrossRefError: build gate aborted because one or more DOIs in
the bibliography failed CrossRef verification. Per PRD section 6.7.T2 + R17
the default is fail-closed; operators bypass with ``allow_unverified_dois=True``
(CLI flag ``--allow-unverified-dois``). The legacy alias
``DOICrossRefFailure`` is preserved as a backwards-compatible re-export.
"""

from __future__ import annotations


class RenderingError(Exception):
    """Base class for REN-namespace rendering errors."""

    error_code: str = "REN000"


class DOICrossRefError(RenderingError):
    """REN001 - one or more DOIs in references.bib failed CrossRef verification.

    Carries the offending DOIs in ``unverified_dois`` so the operator can see
    exactly which entries to repair.
    """

    error_code = "REN001"

    def __init__(self, unverified_dois: list[str]) -> None:
        """Build the error with the list of DOIs that failed verification."""
        self.unverified_dois = list(unverified_dois)
        joined = ", ".join(self.unverified_dois) if self.unverified_dois else "(none)"
        super().__init__(
            f"REN001 DOI CrossRef gate failed for {len(self.unverified_dois)} entry "
            f"(unverified DOIs: {joined}). Pass --allow-unverified-dois to override."
        )


# Back-compat alias for callers that named the class with the older "Failure"
# suffix; preserved so this rename does not break in-flight imports.
DOICrossRefFailure = DOICrossRefError


class AuthorsYamlMissingError(RenderingError):
    """REN002 - authors.yaml absent or invalid at compile time.

    Carries ``searched_paths`` so the operator sees exactly where the loader
    looked. Raised by ``runtime/authors_yaml.py::load_authors_yaml`` and by
    the ``LatexCompilerNode`` build gate per PRD section 6.7.T3.
    """

    error_code = "REN002"

    def __init__(
        self,
        searched_paths: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        """Build the error with the paths searched and an optional reason."""
        self.searched_paths = list(searched_paths) if searched_paths else []
        self.reason = reason
        joined = ", ".join(self.searched_paths) if self.searched_paths else "(none)"
        suffix = f" reason: {reason}" if reason else ""
        super().__init__(f"REN002 authors.yaml missing or invalid (searched: {joined}).{suffix}")


# Back-compat alias — earlier callers used the no-Error-suffix name.
AuthorsYamlMissing = AuthorsYamlMissingError


class TitleTooLongError(RenderingError):
    """REN003 - manuscript title exceeds the 12-word limit.

    Per PRD section 6.7.T4 the formatter's output_validator raises this via
    ``ModelRetry`` so PydanticAI re-prompts once. If the second attempt
    also fails, the agent surfaces ``UnexpectedModelBehavior`` to the
    writing graph and the run aborts.
    """

    error_code = "REN003"
    MAX_WORDS: int = 12

    def __init__(self, title: str, word_count: int) -> None:
        """Build the error with the offending title + its word count."""
        self.title = title
        self.word_count = word_count
        super().__init__(
            f"REN003 title exceeds {self.MAX_WORDS}-word limit "
            f"(got {word_count} words). Title: {title!r}. "
            f"Aim for a 7-10 word declarative title without colon-clause stacks."
        )
