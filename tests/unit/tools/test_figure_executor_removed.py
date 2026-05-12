"""Regression: figure_executor sandbox runner retired by figures-via-dagster
pivot. Importing it must fail so a future contributor who tries to re-introduce
sandbox figure execution gets immediate test-suite feedback.
"""
from __future__ import annotations

import importlib

import pytest


def test_figure_executor_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("academic_pipeline.tools.rendering.figure_executor")


def test_execute_figures_not_re_exported_from_rendering_package() -> None:
    """Even if someone re-adds the module, the package __init__ must not
    re-export it back into academic_pipeline.tools.rendering namespace."""
    from academic_pipeline.tools import rendering

    assert not hasattr(rendering, "execute_figures"), (
        "academic_pipeline.tools.rendering must not re-export execute_figures — "
        "sandbox runner retired by figures-via-dagster pivot."
    )
