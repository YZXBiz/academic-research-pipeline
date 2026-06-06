"""Tests for Spec 7: exploration breadth — design bundling + scoring + selection.

Phase 1 covers model construction, DesignSelectionNode top-K behaviour,
DesignComparisonNode chosen_design_id wiring, and routing of the bundle path
under the exploration_breadth_enabled flag.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from academic_pipeline.config import PipelineConfig
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.experiment.state import ExperimentState
from academic_pipeline.models.experiment import (
    DatasetSpec,
    DesignAlternative,
    DesignBundle,
    DesignComparison,
    DesignScore,
    ExperimentPlan,
    ExperimentResults,
    MethodSpec,
    SelectedDesigns,
)


# -----------------------------
# Helpers
# -----------------------------


def _make_plan(suffix: str = "A") -> ExperimentPlan:
    return ExperimentPlan(
        research_question=f"Q-{suffix}",
        hypothesis=f"H-{suffix}",
        experiment_type="benchmark_comparison",
        dataset_sources=[
            DatasetSpec(
                name=f"ds-{suffix}",
                source="huggingface",
                download_instruction=(
                    "from datasets import load_dataset; "
                    "ds = load_dataset('scikit-learn/adult-census-income')"
                ),
                expected_shape="48k x 15",
                target_column="income",
            )
        ],
        baseline_methods=[
            MethodSpec(name="LR", implementation="LogisticRegression()", is_baseline=True)
        ],
        proposed_methods=[
            MethodSpec(name=suffix, implementation=f"{suffix}()", is_baseline=False)
        ],
        evaluation_metrics=["accuracy"],
        success_criteria="primary metric improves",
    )


def _make_alt(design_id: str, suffix: str | None = None) -> DesignAlternative:
    return DesignAlternative(
        design_id=design_id,
        design=_make_plan(suffix or design_id),
        rationale=f"Tradeoff rationale for {design_id}.",
    )


def _make_score(design_id: str, overall: float, *, fit: float = 7.0) -> DesignScore:
    return DesignScore(
        design_id=design_id,
        data_availability_score=8.0,
        methodological_fit_score=fit,
        expected_discriminative_power=7.0,
        risk_score=8.0,
        overall_score=overall,
        selection_rationale=f"Score rationale for {design_id}.",
    )


def _make_results() -> ExperimentResults:
    return ExperimentResults(
        success=True,
        metrics={"LR": {"accuracy": 0.80}, "D1": {"accuracy": 0.85}},
    )


def _make_deps(*, breadth: bool, n: int = 4, k: int = 2) -> PipelineDeps:
    config = PipelineConfig(
        tool_call_delay_seconds=0,
        exploration_breadth_enabled=breadth,
        n_design_alternatives=n,
        k_designs_to_run=k,
    )
    return PipelineDeps.create(config=config)


# -----------------------------
# 1. Model construction + frozenness
# -----------------------------


def test_design_alternative_constructs_and_is_frozen() -> None:
    alt = _make_alt("D1")
    assert alt.design_id == "D1"
    assert alt.design.research_question == "Q-D1"
    with pytest.raises(ValidationError):
        alt.design_id = "D9"  # type: ignore[misc]


def test_design_bundle_holds_alternatives() -> None:
    bundle = DesignBundle(alternatives=[_make_alt(f"D{i}") for i in range(1, 5)])
    assert [a.design_id for a in bundle.alternatives] == ["D1", "D2", "D3", "D4"]
    with pytest.raises(ValidationError):
        bundle.alternatives = []  # type: ignore[misc]


def test_design_score_validates_score_range() -> None:
    with pytest.raises(ValidationError):
        DesignScore(
            design_id="D1",
            data_availability_score=11.0,  # out of range
            methodological_fit_score=7.0,
            expected_discriminative_power=7.0,
            risk_score=7.0,
            overall_score=7.0,
            selection_rationale="x",
        )


def test_design_comparison_construction() -> None:
    comp = DesignComparison(
        selected_results={"D1": _make_results()},
        comparison_table="| method | acc |\n|---|---|\n| D1 | 0.85 |",
        discussion_paragraph="We considered LR and D1 ...",
        chosen_design_id="D1",
    )
    assert comp.chosen_design_id == "D1"
    assert "D1" in comp.selected_results


# -----------------------------
# 2. DesignSelectionNode top-K behaviour
# -----------------------------


@pytest.mark.parametrize("k", [1, 2, 3])
@pytest.mark.asyncio
async def test_design_selection_picks_top_k_by_overall_score(
    monkeypatch: pytest.MonkeyPatch, k: int
) -> None:
    """Top-K selection must order by overall_score descending."""
    from academic_pipeline.experiment import graph as graph_mod
    from academic_pipeline.experiment.graph import DesignSelectionNode

    alts = [_make_alt(f"D{i}") for i in range(1, 5)]  # D1..D4
    # Highest overall_score first when ordered: D3 (9.5), D1 (8.0), D4 (6.0), D2 (4.5)
    score_map = {
        "D1": 8.0,
        "D2": 4.5,
        "D3": 9.5,
        "D4": 6.0,
    }

    state = ExperimentState(topic="t", rq_brief="rq")
    state.design_bundle = DesignBundle(alternatives=alts)
    deps = _make_deps(breadth=True, k=k)

    async def fake_traced_agent_run(agent, ctx_text, **kwargs):
        # Find which design is being scored from the context text
        for did in ["D1", "D2", "D3", "D4"]:
            marker = f"design_id={did}"
            if marker in ctx_text:
                result = MagicMock()
                result.output = _make_score(did, score_map[did])
                return result
        raise AssertionError("No design_id found in scorer context")

    monkeypatch.setattr(graph_mod, "traced_agent_run", fake_traced_agent_run)

    node = DesignSelectionNode()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    next_node = await node.run(ctx)

    assert next_node.__class__.__name__ == "ConfigWriterNode"
    selected = state.selected_designs
    assert selected is not None

    expected_order = ["D3", "D1", "D4", "D2"]
    assert [a.design_id for a in selected.selected] == expected_order[:k]
    # not_selected is the remainder, in score-descending order
    assert [a.design_id for a in selected.not_selected] == expected_order[k:]
    # All N scores retained
    assert {s.design_id for s in selected.scores} == {"D1", "D2", "D3", "D4"}
    # state.plan = highest-scoring design's plan (Phase 1: only top-1 runs)
    assert state.plan == alts[2].design  # D3 is index 2 (D1=0, D2=1, D3=2, D4=3)


# -----------------------------
# 3. DesignComparisonNode wiring
# -----------------------------


@pytest.mark.asyncio
async def test_design_comparison_chosen_id_matches_top_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DesignComparisonNode wires chosen_design_id from selected[0]."""
    from academic_pipeline.experiment import graph as graph_mod
    from academic_pipeline.experiment.graph import DesignComparisonNode

    alts = [_make_alt("D1"), _make_alt("D2"), _make_alt("D3")]
    state = ExperimentState(topic="t", rq_brief="rq")
    # Order = [D2, D1, D3] — D2 should be chosen
    state.selected_designs = SelectedDesigns(
        selected=[alts[1], alts[0]],
        not_selected=[alts[2]],
        scores=[
            _make_score("D1", 7.0),
            _make_score("D2", 9.0),
            _make_score("D3", 5.0),
        ],
    )
    state.results = _make_results()

    expected = DesignComparison(
        selected_results={"D2": state.results},
        comparison_table="| method | acc |\n|---|---|",
        discussion_paragraph="We considered ...",
        chosen_design_id="D2",
    )

    captured: dict[str, str] = {}

    async def fake_traced_agent_run(agent, ctx_text, **kwargs):
        captured["ctx"] = ctx_text
        result = MagicMock()
        result.output = expected
        return result

    monkeypatch.setattr(graph_mod, "traced_agent_run", fake_traced_agent_run)

    node = DesignComparisonNode()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = _make_deps(breadth=True)

    end_node = await node.run(ctx)

    assert end_node.__class__.__name__ == "End"
    assert state.design_comparison is not None
    assert state.design_comparison.chosen_design_id == "D2"
    # Sanity: the prompt told the comparator that D2 is the chosen design
    assert "chosen_design_id is D2" in captured["ctx"]


# -----------------------------
# 4. Flag-off vs flag-on routing of ExperimentDesignNode
# -----------------------------


@pytest.mark.asyncio
async def test_experiment_design_node_flag_off_uses_single_designer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off: ExperimentDesignNode runs the legacy experiment_designer agent."""
    from academic_pipeline.experiment import graph as graph_mod
    from academic_pipeline.experiment.graph import ConfigWriterNode, ExperimentDesignNode

    state = ExperimentState(topic="t", rq_brief="rq")
    deps = _make_deps(breadth=False)

    plan = _make_plan("legacy")
    eval_calls: list[str] = []

    async def fake_run_with_evaluation(*, agent, context, rubric, deps, name, phase):
        eval_calls.append(name)
        result = MagicMock()
        result.output = plan
        return result

    async def fake_traced_agent_run(agent, ctx_text, **kwargs):  # pragma: no cover - must NOT fire
        raise AssertionError(
            "Bundle path agents must not be invoked when exploration_breadth_enabled=False"
        )

    monkeypatch.setattr(graph_mod, "run_with_evaluation", fake_run_with_evaluation)
    monkeypatch.setattr(graph_mod, "traced_agent_run", fake_traced_agent_run)

    node = ExperimentDesignNode()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    next_node = await node.run(ctx)

    assert isinstance(next_node, ConfigWriterNode)
    assert state.plan == plan
    assert state.design_bundle is None
    assert eval_calls == ["experiment_designer"]


@pytest.mark.asyncio
async def test_experiment_design_node_flag_on_routes_to_bundle() -> None:
    """Flag on: ExperimentDesignNode dispatches directly to ExperimentDesignBundleNode."""
    from academic_pipeline.experiment.graph import (
        ExperimentDesignBundleNode,
        ExperimentDesignNode,
    )

    state = ExperimentState(topic="t", rq_brief="rq")
    deps = _make_deps(breadth=True)

    node = ExperimentDesignNode()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    next_node = await node.run(ctx)
    assert isinstance(next_node, ExperimentDesignBundleNode)
    # ExperimentDesignNode must NOT itself produce a plan when delegating
    assert state.plan is None


@pytest.mark.asyncio
async def test_experiment_design_bundle_node_populates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ExperimentDesignBundleNode stores the DesignBundle on state and routes to selection."""
    from academic_pipeline.experiment import graph as graph_mod
    from academic_pipeline.experiment.graph import (
        DesignSelectionNode,
        ExperimentDesignBundleNode,
    )

    state = ExperimentState(topic="t", rq_brief="rq")
    deps = _make_deps(breadth=True, n=4)
    bundle = DesignBundle(alternatives=[_make_alt(f"D{i}") for i in range(1, 5)])

    async def fake_traced_agent_run(agent, ctx_text, **kwargs):
        assert "N=4" in ctx_text  # bundle node appends the N constraint
        result = MagicMock()
        result.output = bundle
        return result

    monkeypatch.setattr(graph_mod, "traced_agent_run", fake_traced_agent_run)

    node = ExperimentDesignBundleNode()
    ctx = MagicMock()
    ctx.state = state
    ctx.deps = deps

    next_node = await node.run(ctx)
    assert isinstance(next_node, DesignSelectionNode)
    assert state.design_bundle is bundle


# -----------------------------
# 5. Graph & state plumbing
# -----------------------------


def test_state_carries_bundle_fields_with_default_none() -> None:
    state = ExperimentState(topic="t")
    assert state.design_bundle is None
    assert state.selected_designs is None
    assert state.design_comparison is None


def test_build_experiment_graph_includes_new_nodes() -> None:
    from academic_pipeline.experiment.graph import build_experiment_graph

    g = build_experiment_graph()
    assert g.name == "experiment"
    # Graph object exists; node coverage asserted via separate import
    from academic_pipeline.experiment import graph as graph_mod

    for cls in (
        "ExperimentDesignNode",
        "ExperimentDesignBundleNode",
        "DesignSelectionNode",
        "AnalysisNode",
        "DesignComparisonNode",
    ):
        assert hasattr(graph_mod, cls), f"{cls} missing from experiment.graph"
