"""Invariant tests for the numbered phase-directory prefixes.

run-0514 surfaced a collision: `02-experiment` and `02-writing` both
shared the `02-` prefix because the experiment phase was added without
renumbering. These tests are the "can't drift again" guard — they fail
if any two phase dirs share a numeric prefix or if the prefixes fall
out of pipeline order.
"""

from __future__ import annotations

from academic_pipeline.core.enums import PHASE_DIRS, Stage


def test_phase_dirs_cover_every_dir_producing_stage() -> None:
    """Every stage that writes a numbered output dir has a PHASE_DIRS entry.

    FINALIZE/SUMMARY don't write their own numbered phase dir (they finish
    the run); the dir-producing stages are the rest.
    """
    dir_producing = {
        Stage.RESEARCH,
        Stage.EXPERIMENT,
        Stage.WRITE,
        Stage.PRE_INTEGRITY,
        Stage.REVIEW,
        Stage.FINAL_INTEGRITY,
    }
    assert set(PHASE_DIRS) == dir_producing


def test_numeric_prefixes_are_unique() -> None:
    """No two phase dirs may share a numeric prefix — the run-0514 bug."""
    prefixes = [d.split("-", 1)[0] for d in PHASE_DIRS.values()]
    assert len(prefixes) == len(set(prefixes)), f"prefix collision in {PHASE_DIRS}"


def test_prefixes_are_contiguous_from_01() -> None:
    """Prefixes are 01, 02, 03, ... with no gaps."""
    prefixes = sorted(int(d.split("-", 1)[0]) for d in PHASE_DIRS.values())
    assert prefixes == list(range(1, len(prefixes) + 1))


def test_prefix_order_matches_pipeline_stage_order() -> None:
    """The numeric prefix order matches the order stages run in the pipeline."""
    pipeline_order = [
        Stage.RESEARCH,
        Stage.EXPERIMENT,
        Stage.WRITE,
        Stage.PRE_INTEGRITY,
        Stage.REVIEW,
        Stage.FINAL_INTEGRITY,
    ]
    by_prefix = sorted(PHASE_DIRS, key=lambda s: PHASE_DIRS[s])
    assert by_prefix == pipeline_order


def test_writing_dir_no_longer_collides_with_experiment() -> None:
    """Regression: the specific 02- collision from run-0514 is gone."""
    assert PHASE_DIRS[Stage.EXPERIMENT] == "02-experiment"
    assert PHASE_DIRS[Stage.WRITE] == "03-writing"
    assert PHASE_DIRS[Stage.WRITE] != PHASE_DIRS[Stage.EXPERIMENT]
