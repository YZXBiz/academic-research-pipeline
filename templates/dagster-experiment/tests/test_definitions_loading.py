"""Definitions.py must load cleanly with the empty assets/experiment/ package
AND with generated experiment modules. Auto-discovery is the contract that
lets the LLM-generated assets plug in without changing the template.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_definitions_loads_with_no_experiment_assets() -> None:
    """Empty assets/experiment/ package: only data_load is loaded."""
    # Force re-import to clear any prior pkgutil scan.
    for mod in list(sys.modules):
        if mod.startswith("pipeline."):
            sys.modules.pop(mod)
    from pipeline import definitions as defs_mod

    defs = defs_mod.defs()
    asset_keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}
    assert "raw_data" in asset_keys


def test_definitions_discovers_generated_experiment_module(tmp_path: Path, monkeypatch) -> None:
    """Drop a fake @asset module into assets/experiment/, confirm it loads."""
    # Find the actual workspace pipeline.assets.experiment package on disk
    import pipeline.assets.experiment as exp_pkg

    pkg_dir = Path(exp_pkg.__file__).parent
    test_module_path = pkg_dir / "_test_generated_asset.py"
    # NOTE: name starts with underscore so the auto-loader's filter would
    # skip it — but we test the loader's contract: it must skip leading-_
    # modules. Let's drop one without the underscore for the positive case.
    test_module_path = pkg_dir / "test_generated_asset.py"
    test_module_path.write_text(
        '"""Generated test asset."""\n'
        "from dagster import asset\n"
        "\n"
        "@asset(group_name='generated')\n"
        "def my_generated_asset() -> int:\n"
        "    return 42\n"
    )
    try:
        # Clear caches and reload
        for mod in list(sys.modules):
            if mod.startswith("pipeline."):
                sys.modules.pop(mod)
        from pipeline import definitions as defs_mod

        defs = defs_mod.defs()
        asset_keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}
        assert "my_generated_asset" in asset_keys
        assert "raw_data" in asset_keys  # _common still loads too
    finally:
        test_module_path.unlink(missing_ok=True)
        for mod in list(sys.modules):
            if mod.startswith("pipeline."):
                sys.modules.pop(mod)


def test_modules_starting_with_underscore_are_skipped(tmp_path: Path) -> None:
    """Helper modules (_utils.py etc.) under assets/experiment/ must not be loaded as assets."""
    import pipeline.assets.experiment as exp_pkg

    pkg_dir = Path(exp_pkg.__file__).parent
    helper_path = pkg_dir / "_should_be_skipped.py"
    helper_path.write_text(
        '"""Helper module — NOT a Dagster asset module."""\n'
        "from dagster import asset\n"
        "\n"
        "@asset\n"
        "def should_not_appear() -> int:\n"
        "    return 0\n"
    )
    try:
        for mod in list(sys.modules):
            if mod.startswith("pipeline."):
                sys.modules.pop(mod)
        from pipeline import definitions as defs_mod

        defs = defs_mod.defs()
        asset_keys = {key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()}
        assert "should_not_appear" not in asset_keys
    finally:
        helper_path.unlink(missing_ok=True)
        for mod in list(sys.modules):
            if mod.startswith("pipeline."):
                sys.modules.pop(mod)
