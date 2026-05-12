"""Integration test scaffold for the v2 experiment phase.

Full end-to-end runs Dagster + AutoGluon as a subprocess and is too expensive
for routine CI. The actual smoke validation runs manually via:

    cd templates/dagster-experiment && uv run pytest -m medium

This test file exists to capture the wiring sketch so future contributors know
where to add a real e2e test if/when CI infra supports it."""
from __future__ import annotations

import pytest


@pytest.mark.large
def test_v2_experiment_phase_end_to_end() -> None:
    """Skipped by default — real Dagster + AutoGluon subprocess is ~10min.

    Outline (run manually):
      1. Copy templates/dagster-experiment/tests/fixtures/iris.csv into a temp dataset dir.
      2. Stub config_writer agent to return a known-good config.yaml pointing at that dir.
      3. Stub experiment_designer to return a minimal ExperimentPlan.
      4. Run the experiment subgraph; assert AnalysisNode is reached and ctx.state.results
         is populated from results.json.
    """
    pytest.skip(
        "Manual run only — full e2e requires Dagster subprocess + AutoGluon (~10min). "
        "Use templates/dagster-experiment/tests/test_e2e_clustering.py for the e2e validation."
    )
