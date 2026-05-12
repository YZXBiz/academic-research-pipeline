"""Output types for the interactive experiment phase."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExperimentComplete(BaseModel):
    """ML agent signals successful experiment completion."""

    model_config = ConfigDict(frozen=True)

    results_summary: str
    results_json_path: str = "/workspace/results.json"
    figures_dir: str = "/workspace/figures"
    seeds_run: list[int] = Field(default_factory=lambda: [42, 123, 456])


class ExperimentFailed(BaseModel):
    """ML agent signals it cannot complete the experiment."""

    model_config = ConfigDict(frozen=True)

    failure_reason: str
    partial_results: str | None = None


class JudgeVerdict(BaseModel):
    """Judge agent's evaluation of the experiment."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["APPROVED", "MODIFY"]
    checklist: dict[str, bool] = Field(default_factory=dict)
    suggestions: list[str] = Field(default_factory=list)
    further_experiments: list[str] = Field(default_factory=list)
