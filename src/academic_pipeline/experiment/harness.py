# academic_pipeline/experiment/harness.py
"""PydanticAI-native enforcement harness for the interactive ML agent.

5 layers:
1. PrepareTools — force template call before container tools
2. before_tool_execute — block raw ML library imports
3. after_tool_execute — mark template called
4. after_tool_execute — post-run sensor on results.json
5. output_validator — validate ExperimentComplete has real results
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import PrepareTools
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.exceptions import ModelRetry

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.tools import ToolDefinition

    from academic_pipeline.models.experiment import ExperimentPlan
    from academic_pipeline.models.experiment_output import ExperimentComplete, ExperimentFailed
    from academic_pipeline.core.deps import PipelineDeps

logger = logging.getLogger(__name__)

FORBIDDEN_IMPORTS = frozenset({
    "import lightgbm", "import xgboost", "import catboost",
    "from lightgbm", "from xgboost", "from catboost",
    "from sklearn.ensemble", "from sklearn.linear_model",
    "from sklearn.svm", "from sklearn.tree",
    "from sklearn.neural_network",
    "from statsforecast", "import statsforecast",
    "from gluonts", "import gluonts",
    "from chronos", "import chronos",
    "from transformers", "import transformers",
    "from timm", "import timm",
})

ALLOWED_SKLEARN = frozenset({
    "from sklearn.dummy",
    "from sklearn.model_selection",
    "from sklearn.metrics",
    "from sklearn.preprocessing",
})

ALLOWED_AUTOGLUON = frozenset({
    "from autogluon.tabular",
    "from autogluon.timeseries",
    "from autogluon.multimodal",
    "from autogluon.core",
    "import autogluon",
})

TEMPLATE_MAP: dict[str, str] = {
    "tabular": "get_autogluon_tabular_template",
    "timeseries": "get_autogluon_timeseries_template",
    "multimodal": "get_autogluon_multimodal_template",
}


# --- Layer 1: Template-first gate ---

async def _enforce_template_first(
    ctx: RunContext[PipelineDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition]:
    if not ctx.deps.template_called:
        allowed = {TEMPLATE_MAP[ctx.deps.predictor_type], "get_autogluon_presets_info"}
        return [td for td in tool_defs if td.name in allowed]
    return tool_defs

template_gate = PrepareTools(_enforce_template_first)


# --- Layers 2-4: Hooks ---

harness_hooks = Hooks()


@harness_hooks.on.after_tool_execute(tools=[
    "get_autogluon_tabular_template",
    "get_autogluon_timeseries_template",
    "get_autogluon_multimodal_template",
])
async def mark_template_called(
    ctx: RunContext[PipelineDeps],
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    result: Any,
) -> Any:
    ctx.deps.template_called = True
    return result


@harness_hooks.on.before_tool_execute(tools=["create_file", "write_file"])
async def block_raw_ml_imports(
    ctx: RunContext[PipelineDeps],
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
) -> dict[str, Any]:
    content = args.get("content", "")
    for line in content.split("\n"):
        stripped = line.strip()
        if any(stripped.startswith(f) for f in FORBIDDEN_IMPORTS):
            if any(stripped.startswith(a) for a in ALLOWED_SKLEARN):
                continue
            if any(stripped.startswith(a) for a in ALLOWED_AUTOGLUON):
                continue
            raise ModelRetry(
                f"BLOCKED: '{stripped}' is not allowed. "
                "Use the AutoGluon Predictor API instead — it wraps internal "
                "libraries automatically. Import from autogluon.tabular, "
                "autogluon.timeseries, or autogluon.multimodal."
            )
    return args


@harness_hooks.on.after_tool_execute(tools=["run_python"])
async def post_run_sensor(
    ctx: RunContext[PipelineDeps],
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    result: Any,
) -> Any:
    env = ctx.deps.docker_env
    if env is None:
        return result
    sensor_lines: list[str] = []
    check = env.run_command("test -f /workspace/results.json && echo EXISTS")
    if check["status"] == 0 and "EXISTS" in check["result"]:
        sensor_lines.append("[SENSOR] results.json found")
    figs = env.run_command("ls /workspace/figures/*.png 2>/dev/null | wc -l")
    if figs["status"] == 0 and figs["result"].strip() not in ("0", ""):
        sensor_lines.append(f"[SENSOR] {figs['result'].strip()} figure(s) in /workspace/figures/")
    if sensor_lines:
        return str(result) + "\n\n" + "\n".join(sensor_lines)
    return result


# --- Layer 5: Output validator (applied via decorator in agents.py) ---

async def validate_experiment_output(
    ctx: RunContext[PipelineDeps],
    output: ExperimentComplete | ExperimentFailed,
) -> ExperimentComplete | ExperimentFailed:
    from academic_pipeline.models.experiment_output import ExperimentFailed as EF

    logger.debug("validate_experiment_output called: type=%s, docker_env=%s", type(output).__name__, ctx.deps.docker_env)

    if isinstance(output, EF):
        return output

    env = ctx.deps.docker_env
    if env is None:
        raise ModelRetry("Docker container not initialized")

    check = env.run_command(f"cat {output.results_json_path}")
    if check["status"] != 0:
        raise ModelRetry(
            f"results.json not found at {output.results_json_path}. "
            "Run the experiment first with run_python."
        )

    try:
        data = json.loads(check["result"])
    except json.JSONDecodeError:
        raise ModelRetry("results.json is not valid JSON.")

    if not data.get("metrics"):
        raise ModelRetry("results.json has no 'metrics' key.")

    if len(output.seeds_run) < 3:
        raise ModelRetry(
            f"Only {len(output.seeds_run)} seeds run. Need 3 (42, 123, 456)."
        )

    return output


# --- Layer 6: Plan output validator (applied via decorator in agents.py) ---

_PREDICTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tabular": ("autogluon", "tabularpredictor"),
    "timeseries": ("autogluon", "timeseriespredictor"),
    "multimodal": ("autogluon", "multimodalpredictor"),
}


async def validate_experiment_plan(
    ctx: RunContext[PipelineDeps],
    output: ExperimentPlan,
) -> ExperimentPlan:
    predictor_type = ctx.deps.predictor_type
    keywords = _PREDICTOR_KEYWORDS[predictor_type]
    names = " ".join(
        m.name.lower() + " " + m.implementation.lower()
        for m in output.proposed_methods
    )
    if not any(k in names for k in keywords):
        raise ModelRetry(
            f"proposed_methods must include AutoGluon "
            f"{keywords[-1]} for predictor_type='{predictor_type}'."
        )
    return output
