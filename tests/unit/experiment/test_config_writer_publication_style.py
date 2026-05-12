"""config_writer.yaml must instruct the LLM to use the workspace's
publication-quality matplotlib style + save PDFs (not PNGs).
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _spec() -> dict:
    raw = Path("src/academic_pipeline/experiment/specs/config_writer.yaml").read_text()
    return yaml.safe_load(raw)


def test_config_writer_mentions_apply_pub_style() -> None:
    instructions = _spec()["instructions"].lower()
    assert "apply_pub_style" in instructions, (
        "config_writer.yaml must teach the LLM to call apply_pub_style() in "
        "generated figures.py modules so figures match journal typography."
    )


def test_config_writer_mentions_pdf_savefig() -> None:
    instructions = _spec()["instructions"].lower()
    has_pdf = ".pdf" in instructions or "save as pdf" in instructions or (
        "savefig" in instructions and "pdf" in instructions
    )
    assert has_pdf, (
        "config_writer.yaml must teach the LLM to save figures as .pdf "
        "(vector) instead of .png (raster — gets rejected on figure-quality "
        "review)."
    )


def test_config_writer_mentions_column_width_helper() -> None:
    instructions = _spec()["instructions"].lower()
    assert "column_width_inches" in instructions or "column width" in instructions, (
        "config_writer.yaml must teach the LLM to size figures at column "
        "width via the helper, not the matplotlib default 8x6."
    )
