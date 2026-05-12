"""Authors YAML loader for the §6.7.T3 build gate.

Schema per OQ13: a list of ``{name, affiliation, email?, orcid?}`` mappings.
Two file shapes are accepted at load time:

    - top-level list:
        - name: ...
          affiliation: ...

    - nested under an ``authors:`` key:
        authors:
          - name: ...
            affiliation: ...

Both round-trip to the same ``list[AuthorsYamlEntry]``. Loader raises
``AuthorsYamlMissing`` (REN002) when the file is absent OR fails schema
validation; the gate inside ``LatexCompilerNode`` propagates that to abort
the build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from academic_pipeline.runtime.rendering_errors import AuthorsYamlMissing


if TYPE_CHECKING:
    from pathlib import Path


class AuthorsYamlEntry(BaseModel):
    """One author entry in authors.yaml. Per OQ13."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    affiliation: str = ""
    email: str | None = None
    orcid: str | None = None


def resolve_authors_yaml_path(*candidates: Path) -> Path | None:
    """Return the first ``<candidate>/authors.yaml`` that exists, else ``None``.

    Resolution is order-sensitive: callers pass run-dir before repo-root so
    a per-run override beats the project default.
    """
    for candidate in candidates:
        if candidate is None:  # pragma: no cover - defensive against caller bugs
            continue
        target = candidate / "authors.yaml"
        if target.is_file():
            return target
    return None


def load_authors_yaml(path: Path) -> list[AuthorsYamlEntry]:
    """Load + validate authors.yaml at ``path``.

    Args:
        path: absolute or repo-relative path to ``authors.yaml``.

    Returns:
        A non-empty list of ``AuthorsYamlEntry``.

    Raises:
        AuthorsYamlMissing (REN002): file does not exist; YAML parse fails;
            top-level shape isn't a list / ``authors:`` mapping; the list is
            empty; any entry fails schema validation (missing ``name``,
            unknown extra keys, etc.).
    """
    if not path.is_file():
        raise AuthorsYamlMissing(searched_paths=[str(path)])

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise AuthorsYamlMissing(
            searched_paths=[str(path)],
            reason=f"yaml parse error: {e}",
        ) from e

    items: object
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and "authors" in raw:
        items = raw["authors"]
    else:
        raise AuthorsYamlMissing(
            searched_paths=[str(path)],
            reason="top-level must be a list or a mapping with an 'authors:' key",
        )

    if not isinstance(items, list) or not items:
        raise AuthorsYamlMissing(
            searched_paths=[str(path)],
            reason="'authors' must be a non-empty list",
        )

    try:
        return [AuthorsYamlEntry.model_validate(entry) for entry in items]
    except ValidationError as e:
        raise AuthorsYamlMissing(
            searched_paths=[str(path)],
            reason=f"schema validation failed: {e.errors()[0]['msg']}",
        ) from e
