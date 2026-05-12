"""Docker integration tests for the experiment harness.

These tests start a real Docker container and execute real code inside it.
Only the LLM decisions are scripted via FunctionModel.

Requires:
  - Docker daemon running
  - academic-pipeline-sandbox:latest image (make docker-build)

Run: make test-integration
     uv run pytest -m medium -v
"""
from __future__ import annotations

import json

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from academic_pipeline.config import PipelineConfig
from academic_pipeline.experiment.agents import agents as experiment_agents
from academic_pipeline.core.deps import PipelineDeps
from academic_pipeline.tools.execution.docker_env import DockerConfig, DockerEnv

pytestmark = pytest.mark.medium

_EXPERIMENT_SCRIPT = '''\
import json, os
os.makedirs("figures", exist_ok=True)
results = {
    "success": True,
    "metrics": {
        "seed_42": {"accuracy": 0.95},
        "seed_123": {"accuracy": 0.94},
        "seed_456": {"accuracy": 0.96},
    },
}
json.dump(results, open("results.json", "w"), indent=2)
print("Done")
'''

_FINAL_OUTPUT = json.dumps({
    "result": {
        "kind": "ExperimentComplete",
        "data": {
            "results_summary": "AutoGluon on Iris. 3 seeds.",
            "results_json_path": "/workspace/results.json",
            "figures_dir": "/workspace/figures",
            "seeds_run": [42, 123, 456],
        },
    }
})


@pytest.fixture(scope="session")
def docker_container(tmp_path_factory):
    """Start a real Docker container for the test session."""
    local_root = str(tmp_path_factory.mktemp("experiment"))
    config = DockerConfig(container_name="test-experiment-sandbox", local_root=local_root)
    env = DockerEnv(config)
    env.init_container()
    yield env
    env.stop_container()


@pytest.fixture(autouse=True)
def clean_workspace(docker_container):
    """Clean /workspace between tests for isolation."""
    docker_container.run_command("find /workspace -maxdepth 1 -not -name workspace -not -name .venv -not -name pyproject.toml -not -name uv.lock -not -name .python-version -exec rm -rf {} + 2>/dev/null || true")
    yield


@pytest.fixture()
def experiment_deps(docker_container):
    """PipelineDeps with real Docker container attached."""
    config = PipelineConfig(
        anthropic_api_key="sk-test-fake-key",  # type: ignore[arg-type]
        model_name="test",
        max_budget_tokens=999_999,
        tool_call_delay_seconds=0,
    )
    deps = PipelineDeps.create(config=config)
    deps.docker_env = docker_container
    deps.template_called = False
    return deps


def _count_tool_returns(messages: list[ModelMessage]) -> list[str]:
    """Extract completed tool names from message history."""
    completed: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    completed.append(part.tool_name)
    return completed


def _happy_path_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Script: template -> create_file -> run_python -> ExperimentComplete."""
    completed = _count_tool_returns(messages)

    if "get_autogluon_tabular_template" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="get_autogluon_tabular_template",
            args={
                "task_type": "classification",
                "eval_metric": "accuracy",
                "target_column": "target",
                "dataset_load_code": "pass",
            },
            tool_call_id="step_1",
        )])

    if "create_file" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="create_file",
            args={"path": "/workspace/experiment.py", "content": _EXPERIMENT_SCRIPT},
            tool_call_id="step_2",
        )])

    if "run_python" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="run_python",
            args={"script_path": "/workspace/experiment.py"},
            tool_call_id="step_3",
        )])

    return ModelResponse(parts=[TextPart(content=_FINAL_OUTPUT)])


@pytest.mark.asyncio
async def test_ml_engineer_full_experiment(experiment_deps):
    """Full happy path: template -> write code -> run -> ExperimentComplete."""
    agent = experiment_agents["ml_engineer"]
    with agent.override(model=FunctionModel(_happy_path_fn)):
        result = await agent.run("Run experiment", deps=experiment_deps)

    from academic_pipeline.models.experiment_output import ExperimentComplete

    assert isinstance(result.output, ExperimentComplete)
    assert result.output.seeds_run == [42, 123, 456]

    check = experiment_deps.docker_env.run_command("cat /workspace/results.json")
    assert check["status"] == 0
    data = json.loads(check["result"])
    assert "metrics" in data
    assert data["success"] is True


def _forbidden_import_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Script: template -> create_file with 'import xgboost' -> should be blocked."""
    completed = _count_tool_returns(messages)

    if "get_autogluon_tabular_template" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="get_autogluon_tabular_template",
            args={"task_type": "classification", "eval_metric": "accuracy",
                  "target_column": "t", "dataset_load_code": "pass"},
            tool_call_id="s1",
        )])

    return ModelResponse(parts=[ToolCallPart(
        tool_name="create_file",
        args={"path": "/workspace/bad.py", "content": "import xgboost\nprint('hi')"},
        tool_call_id="s2",
    )])


@pytest.mark.asyncio
async def test_harness_blocks_forbidden_imports(experiment_deps):
    """Harness layer 2 blocks create_file with forbidden imports."""
    agent = experiment_agents["ml_engineer"]
    with agent.override(model=FunctionModel(_forbidden_import_fn)):
        with pytest.raises(UnexpectedModelBehavior, match="retries"):
            await agent.run("Run experiment", deps=experiment_deps)


def _skip_template_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Script: try create_file immediately without calling template first."""
    return ModelResponse(parts=[ToolCallPart(
        tool_name="create_file",
        args={"path": "/workspace/code.py", "content": "print('hello')"},
        tool_call_id="skip",
    )])


@pytest.mark.asyncio
async def test_harness_requires_template_first(experiment_deps):
    """PrepareTools gate blocks tools until template is called."""
    agent = experiment_agents["ml_engineer"]
    with agent.override(model=FunctionModel(_skip_template_fn)):
        with pytest.raises(UnexpectedModelBehavior, match="retries"):
            await agent.run("Run experiment", deps=experiment_deps)


def _no_results_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Script: template -> create harmless file -> claim ExperimentComplete without results.json."""
    completed = _count_tool_returns(messages)

    if "get_autogluon_tabular_template" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="get_autogluon_tabular_template",
            args={"task_type": "classification", "eval_metric": "accuracy",
                  "target_column": "t", "dataset_load_code": "pass"},
            tool_call_id="s1",
        )])

    if "create_file" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="create_file",
            args={"path": "/workspace/hello.py", "content": "print('hello')"},
            tool_call_id="s2",
        )])

    if "run_python" not in completed:
        return ModelResponse(parts=[ToolCallPart(
            tool_name="run_python",
            args={"script_path": "/workspace/hello.py"},
            tool_call_id="s3",
        )])

    return ModelResponse(parts=[TextPart(content=_FINAL_OUTPUT)])


@pytest.mark.asyncio
async def test_output_validator_rejects_missing_results(experiment_deps):
    """Output validator (layer 5) catches missing results.json."""
    agent = experiment_agents["ml_engineer"]
    with agent.override(model=FunctionModel(_no_results_fn)):
        with pytest.raises(UnexpectedModelBehavior, match="retries"):
            await agent.run("Run experiment", deps=experiment_deps)
