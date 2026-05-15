"""Static AST validator for agent-generated Dagster workspaces.

Catches a recurring config_writer hallucination class: @asset modules
declared with `deps=["foo"]` where `foo` isn't a defined asset anywhere
in the workspace (or among the template-shipped names). Dagster
silently treats unknown deps as phantom external assets and the run
either fails opaquely or produces no results.json. The pipeline then
writes a [PENDING]-laden paper because experiment_results is empty.

Run this immediately after the agent writes the workspace, before
kicking Dagster — the errors are intended to feed back into a
config_writer retry.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


# The Dagster template ships one @asset that every agent-generated
# workspace can legitimately depend on: pipeline.assets._common.data_load
# (asset name `raw_data`). It materializes one `raw_<stem>` DuckDB table
# per file in `dataset.files`. Add to this list if the template grows.
_TEMPLATE_ASSETS: frozenset[str] = frozenset({"raw_data"})


@dataclass(frozen=True)
class DepValidationError:
    """One dangling `deps=[...]` reference in an agent-generated @asset."""

    module: str
    asset_name: str
    dangling_dep: str

    def render(self) -> str:
        """Single-line human-readable form, suitable for agent retry feedback."""
        return (
            f"{self.module}: @asset `{self.asset_name}` references "
            f"undefined upstream `{self.dangling_dep}` in deps=[...]. "
            f"Define an upstream @asset with that name or use an existing one."
        )


def validate_dagster_deps(workspace: Path) -> list[DepValidationError]:
    """Walk the agent-generated @asset modules and verify every dep is defined.

    Args:
        workspace: Workspace root (contains src/pipeline/assets/experiment/).

    Returns:
        A list of every dangling-dep error found. Empty list = clean.
    """
    assets_dir = workspace / "src" / "pipeline" / "assets" / "experiment"
    if not assets_dir.is_dir():
        return []

    modules = [p for p in sorted(assets_dir.glob("*.py")) if not p.name.startswith("_")]

    defined: set[str] = set(_TEMPLATE_ASSETS)
    per_module_assets: list[tuple[Path, list[tuple[str, list[str]]]]] = []
    for mod in modules:
        try:
            tree = ast.parse(mod.read_text())
        except SyntaxError:
            # Don't crash on agent syntax errors — Dagster will surface those.
            # Still record what we could parse from other modules.
            continue
        decls = _collect_assets(tree)
        per_module_assets.append((mod, decls))
        for name, _ in decls:
            defined.add(name)

    return [
        DepValidationError(module=mod.name, asset_name=asset_name, dangling_dep=dep)
        for mod, decls in per_module_assets
        for asset_name, deps in decls
        for dep in deps
        if dep not in defined
    ]


def _collect_assets(tree: ast.Module) -> list[tuple[str, list[str]]]:
    """Find every `@asset(deps=[...])` decorated function in the module.

    Returns a list of (asset_name, dep_strings) tuples. The asset name is
    the function name (matches Dagster's default key_prefix=None behavior).
    Strings inside deps=[...] are collected; non-literal expressions are
    skipped (we can't statically resolve them).
    """
    out: list[tuple[str, list[str]]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _has_asset_decorator(node):
            continue
        deps = _extract_deps(node)
        out.append((node.name, deps))
    return out


def _has_asset_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function has @asset or @asset(...) (any call form)."""
    for deco in node.decorator_list:
        # @asset
        if isinstance(deco, ast.Name) and deco.id == "asset":
            return True
        # @asset(...) or @asset(deps=...)
        if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == "asset":
            return True
    return False


def _extract_deps(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Pull string literals out of the `deps=[...]` kwarg on the @asset call."""
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        for kw in deco.keywords:
            if kw.arg != "deps":
                continue
            if not isinstance(kw.value, (ast.List, ast.Tuple)):
                continue
            return [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
    return []
