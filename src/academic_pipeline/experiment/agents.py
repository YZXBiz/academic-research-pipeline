"""Experiment agent registry.

Centralises all Agent.from_file() definitions for the experiment subgraph.
Imported by ``graph.py`` as
``from academic_pipeline.experiment.agents import agents as _agents``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, PromptedOutput, RunContext, Tool
from pydantic_ai_skills import SkillsCapability

from academic_pipeline.config import SKILLS_DIRS
from academic_pipeline.experiment.harness import (
    harness_hooks,
    template_gate,
    validate_experiment_output,
    validate_experiment_plan,
)
from academic_pipeline.models.experiment import (
    DesignBundle,
    DesignComparison,
    DesignScore,
    ExperimentAnalysis,
    ExperimentClassification,
    ExperimentPlan,
    FigureReviewResult,
    WorkspaceFiles,
)
from academic_pipeline.models.experiment_output import (
    ExperimentComplete,
    ExperimentFailed,
    JudgeVerdict,
)
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.tools.bibliography.exa import web_fetch_exa, web_search_exa
from academic_pipeline.tools.execution.autogluon_templates import (
    get_autogluon_multimodal_template,
    get_autogluon_presets_info,
    get_autogluon_tabular_template,
    get_autogluon_timeseries_template,
)
from academic_pipeline.tools.execution.containers import (
    create_directory,
    create_file,
    execute_command,
    gen_code_tree,
    list_files,
    read_file,
    run_python,
    visualize_figure,
    write_file,
)
from academic_pipeline.runtime.throttle import throttle_hooks


_AGENTS_DIR = Path(__file__).parent / "specs"

agents: dict[str, Agent[PipelineDeps, Any]] = {
    "experiment_classifier": Agent.from_file(
        _AGENTS_DIR / "experiment_classifier.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ExperimentClassification),
        capabilities=[throttle_hooks],
    ),
    "experiment_designer": Agent.from_file(
        _AGENTS_DIR / "experiment_designer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ExperimentPlan),
        capabilities=[throttle_hooks],
        tools=[web_search_exa, web_fetch_exa],
    ),
    "result_analyzer": Agent.from_file(
        _AGENTS_DIR / "result_analyzer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ExperimentAnalysis),
        capabilities=[throttle_hooks],
    ),
    "experiment_improver": Agent.from_file(
        _AGENTS_DIR / "experiment_improver.yaml",
        deps_type=PipelineDeps,
        output_type=str,
        capabilities=[throttle_hooks],
    ),
    "figure_reviewer": Agent.from_file(
        _AGENTS_DIR / "figure_reviewer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(FigureReviewResult),
        capabilities=[throttle_hooks],
    ),
    "ml_engineer": Agent.from_file(
        _AGENTS_DIR / "ml_engineer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(ExperimentComplete | ExperimentFailed),
        capabilities=[throttle_hooks, SkillsCapability(directories=SKILLS_DIRS), template_gate, harness_hooks],
        tools=[
            Tool(create_file, max_retries=5),
            Tool(write_file, max_retries=5),
            read_file, list_files, create_directory, gen_code_tree,
            execute_command, run_python,
            get_autogluon_tabular_template, get_autogluon_timeseries_template,
            get_autogluon_multimodal_template, get_autogluon_presets_info,
        ],
        end_strategy="graceful",
    ),
    "experiment_judge": Agent.from_file(
        _AGENTS_DIR / "experiment_judge.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(JudgeVerdict),
        capabilities=[throttle_hooks],
        tools=[read_file, list_files, gen_code_tree, execute_command, visualize_figure],
    ),
    # Spec 7 — exploration breadth (only used when
    # config.exploration_breadth_enabled=True)
    "experiment_designer_bundle": Agent.from_file(
        _AGENTS_DIR / "experiment_designer_bundle.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(DesignBundle),
        capabilities=[throttle_hooks],
        tools=[web_search_exa, web_fetch_exa],
    ),
    "design_scorer": Agent.from_file(
        _AGENTS_DIR / "design_scorer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(DesignScore),
        capabilities=[throttle_hooks],
    ),
    "design_comparator": Agent.from_file(
        _AGENTS_DIR / "design_comparator.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(DesignComparison),
        capabilities=[throttle_hooks],
    ),
    # v2: replaces ml_engineer as the only LLM in the experiment phase.
    # Reads ExperimentPlan, writes a WorkspaceFiles bundle (config.yaml +
    # generated @asset modules under src/pipeline/assets/experiment/).
    "config_writer": Agent.from_file(
        _AGENTS_DIR / "config_writer.yaml",
        deps_type=PipelineDeps,
        output_type=PromptedOutput(WorkspaceFiles),
        capabilities=[throttle_hooks],
    ),
}

# Layer 5: Output validators applied after agent creation
agents["ml_engineer"].output_validator(validate_experiment_output)
agents["experiment_designer"].output_validator(validate_experiment_plan)

# Layer 6: Dynamic instruction injection — predictor_type context
def _inject_predictor_type(ctx: RunContext[PipelineDeps]) -> str:
    return f"The classified predictor type for this experiment is: {ctx.deps.predictor_type}"

for _name in (
    "experiment_designer",
    "ml_engineer",
    "experiment_judge",
    "result_analyzer",
    "experiment_improver",
    "config_writer",
):
    if _name in agents:
        agents[_name].instructions(_inject_predictor_type)
