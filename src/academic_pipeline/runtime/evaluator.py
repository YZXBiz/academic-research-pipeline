"""Per-node 3-model evaluation panel.

Runs output-only evaluation across multiple frontier models in parallel.
Aggregates scores via median. Returns PASS or NEEDS_IMPROVEMENT with
targeted feedback on the weakest dimension.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import Agent, AgentRunResult, PromptedOutput

from academic_pipeline.models.shared import (
    EvaluationResult,
    EvaluatorDetail,
)
from academic_pipeline.recovery.bounded_run import bounded_agent_run
from academic_pipeline.runtime.hard_vetos import VetoFn, apply_hard_vetos


if TYPE_CHECKING:
    from academic_pipeline.core.deps import PipelineDeps

logger = logging.getLogger(__name__)

_EVALUATOR_SYSTEM_PROMPT = """You are an academic quality evaluator. Score the output against the rubric.
Return a JSON object with exactly these fields:
- verdict: "PASS" or "NEEDS_IMPROVEMENT"
- scores: object mapping each rubric dimension to a score 0-10
- feedback: specific, actionable feedback (1-3 sentences)
- weakest_dimension: the dimension name with the lowest score, or null if all pass

Score strictly. Only return "PASS" if ALL dimensions score >= 7 and the average >= the threshold.
If NEEDS_IMPROVEMENT, explain exactly what is weak and how to fix it."""

_evaluator_agents: dict[str, Agent[None, EvaluationResult]] = {}


def _get_evaluator_agent(model_name: str) -> Agent[None, EvaluationResult]:
    """Return a cached evaluator agent for the given model name."""
    if model_name not in _evaluator_agents:
        _evaluator_agents[model_name] = Agent(
            model_name,
            system_prompt=_EVALUATOR_SYSTEM_PROMPT,
            output_type=PromptedOutput(EvaluationResult),
        )
    return _evaluator_agents[model_name]


async def _run_single_evaluator(
    model_name: str,
    output_json: str,
    rubric: str,
    traceability_context: str | None = None,
) -> EvaluationResult:
    """Run a single evaluator model and return its result.

    When traceability_context is provided, prepends a TRACEABILITY CONTEXT
    block before the rubric so the evaluator can verify quantitative claims
    in the output against upstream artifacts (synthesis, experiment_results,
    etc.). This is the core of the anti-fabrication detection.
    """
    agent = _get_evaluator_agent(model_name)
    if traceability_context:
        prompt = (
            f"TRACEABILITY CONTEXT (upstream artifacts the output may reference):\n"
            f"{traceability_context}\n\n"
            f"---\n\n"
            f"Rubric:\n{rubric}\n\n"
            f"Output to evaluate:\n{output_json}"
        )
    else:
        prompt = f"Rubric:\n{rubric}\n\nOutput to evaluate:\n{output_json}"
    result = await bounded_agent_run(agent, prompt, timeout_s=900.0)
    return result.output


def _aggregate_results(pairs: list[tuple[str, EvaluationResult]], threshold: float) -> EvaluationResult:
    """Aggregate multiple evaluation results via median scoring."""
    results = [r for _, r in pairs]

    all_dims: set[str] = set()
    for r in results:
        all_dims.update(r.scores.keys())

    median_scores: dict[str, float] = {}
    for dim in sorted(all_dims):
        values = [r.scores.get(dim, 0.0) for r in results]
        if len(values) == 2:
            median_scores[dim] = min(values)  # conservative: use lower score
        else:
            median_scores[dim] = statistics.median(values)

    # Rubber-stamp warning
    for model_name, r in pairs:
        if r.scores and all(s >= 9.5 for s in r.scores.values()):
            logger.warning(
                "Evaluator %s gave all scores >= 9.5 (possible rubber-stamp): %s",
                model_name,
                dict(r.scores),
            )

    weakest = min(median_scores, key=median_scores.get) if median_scores else None  # type: ignore[arg-type]
    all_pass = all(s >= threshold for s in median_scores.values()) if median_scores else True

    verdict: Literal["PASS", "NEEDS_IMPROVEMENT"] = "PASS" if all_pass else "NEEDS_IMPROVEMENT"

    feedbacks = [f"[{model}] {r.feedback}" for model, r in pairs if r.feedback]
    merged_feedback = " | ".join(feedbacks) if feedbacks else "No feedback."

    per_model = [EvaluatorDetail(model_name=model, scores=dict(r.scores), feedback=r.feedback) for model, r in pairs]

    return EvaluationResult(
        verdict=verdict,
        scores=median_scores,
        feedback=merged_feedback,
        weakest_dimension=weakest if verdict == "NEEDS_IMPROVEMENT" else None,
        per_model=per_model,
    )


async def evaluate_node_output(
    output_json: str,
    rubric: str,
    deps: PipelineDeps,
    threshold: float | None = None,
    traceability_context: str | None = None,
) -> EvaluationResult:
    """Run the 3-model evaluation panel on a node's output.

    When evaluation is disabled, returns PASS immediately. If all evaluators
    fail, returns PASS with a warning. Otherwise, aggregates results via
    median scoring.

    traceability_context: optional upstream artifact text the output may
    reference. When provided, evaluators can verify quantitative claims
    against the upstream artifacts (anti-fabrication detection).
    """
    if not deps.config.enable_node_evaluation:
        return EvaluationResult(
            verdict="PASS",
            scores={},
            feedback="Evaluation disabled.",
            weakest_dimension=None,
        )

    models = deps.config.evaluator_models
    tasks = [_run_single_evaluator(model, output_json, rubric, traceability_context) for model in models]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_pairs: list[tuple[str, EvaluationResult]] = []
    for i, r in enumerate(results):
        if isinstance(r, EvaluationResult):
            valid_pairs.append((models[i], r))
        elif isinstance(r, Exception):
            logger.warning("Evaluator %s failed: %s", models[i], r)

    if not valid_pairs:
        logger.warning("All evaluators failed — defaulting to PASS")
        return EvaluationResult(
            verdict="PASS",
            scores={},
            feedback="All evaluators failed. Proceeding with best effort.",
            weakest_dimension=None,
        )

    effective_threshold = threshold or deps.config.node_quality_threshold
    return _aggregate_results(valid_pairs, effective_threshold)


async def run_with_evaluation(
    agent: Agent[Any, Any],
    context: str,
    rubric: str,
    deps: PipelineDeps,
    max_iterations: int | None = None,
    quality_threshold: float | None = None,
    name: str = "",
    phase: str = "",
    traceability_context: str | None = None,
    hard_vetos: list[VetoFn] | None = None,
) -> AgentRunResult[Any]:
    """Run agent with per-node evaluation loop.

    1. Generate with thinking
    2. Evaluate output with 3-model panel
    3. Apply code-enforced hard vetos (if any) — can override LLM PASS verdict
    4. If PASS or max iterations: return result
    5. If NEEDS_IMPROVEMENT: revise with feedback, re-evaluate

    Monotonic quality gate: if revision scores lower, revert to previous.

    hard_vetos: optional list of veto functions (see hard_vetos module). Each
    is run on the output text after LLM evaluation; if any fires, the verdict
    is forced to NEEDS_IMPROVEMENT and the veto reason is appended to feedback.
    This is the code-enforcement layer that catches what prompt instructions
    and LLM rubrics miss.
    """
    max_iter = max_iterations or deps.config.max_node_iterations
    # PRD §6.12.T5: per-node threshold map with fallback to global default. An
    # explicit `quality_threshold` kwarg still wins over both.
    threshold = quality_threshold or deps.config.get_node_threshold(name)

    best_result = await bounded_agent_run(agent, context, deps=deps, timeout_s=900.0)

    if not deps.config.enable_node_evaluation:
        if deps.trace_logger and name:
            deps.trace_logger.log(name, phase, best_result)
        return best_result

    best_eval = await evaluate_node_output(
        output_json=_output_to_json(best_result.output),
        rubric=rubric,
        deps=deps,
        threshold=threshold,
        traceability_context=traceability_context,
    )
    if hard_vetos:
        best_eval = apply_hard_vetos(_output_to_text(best_result.output), best_eval, hard_vetos)

    # Always log first generation with its eval result
    if deps.trace_logger and name:
        deps.trace_logger.log(name, phase, best_result, eval_result=best_eval)

    if best_eval.verdict == "PASS":
        logger.info("Node evaluation: PASS on first generation")
        return best_result

    for iteration in range(1, max_iter):
        logger.info(
            "Node evaluation: NEEDS_IMPROVEMENT (iter %d/%d) — weakest: %s",
            iteration,
            max_iter,
            best_eval.weakest_dimension,
        )
        feedback_lines = "\n".join(f"- {part.strip()}" for part in best_eval.feedback.split(" | ") if part.strip())
        revision_context = (
            f"{context}\n\n"
            f"[REVISION FEEDBACK from evaluation panel]\n"
            f"Previous output scored below threshold.\n"
            f"Weakest dimension: {best_eval.weakest_dimension}\n\n"
            f"Reviewer feedback:\n{feedback_lines}\n\n"
            f"Please revise to address this specific feedback."
        )

        revised_result = await bounded_agent_run(agent, revision_context, deps=deps, timeout_s=900.0)

        revised_eval = await evaluate_node_output(
            output_json=_output_to_json(revised_result.output),
            rubric=rubric,
            deps=deps,
            threshold=threshold,
            traceability_context=traceability_context,
        )
        if hard_vetos:
            revised_eval = apply_hard_vetos(_output_to_text(revised_result.output), revised_eval, hard_vetos)

        # Log each revision with its eval
        if deps.trace_logger and name:
            deps.trace_logger.log(f"{name}_revision_{iteration}", phase, revised_result, eval_result=revised_eval)

        if revised_eval.verdict == "PASS":
            logger.info("Node evaluation: PASS after revision %d", iteration)
            return revised_result

        revised_avg = statistics.mean(revised_eval.scores.values()) if revised_eval.scores else 0
        best_avg = statistics.mean(best_eval.scores.values()) if best_eval.scores else 0
        if revised_avg > best_avg:
            best_result = revised_result
            best_eval = revised_eval
        else:
            logger.info("Revision scored lower (%.1f vs %.1f) — reverting", revised_avg, best_avg)

    logger.warning(
        "Node evaluation: max iterations reached — accepting sub-threshold result (best verdict: %s, weakest: %s)",
        best_eval.verdict,
        best_eval.weakest_dimension,
    )
    return best_result


def _output_to_json(output: Any) -> str:
    """Convert agent output to JSON string for evaluation."""
    if hasattr(output, "model_dump_json"):
        return output.model_dump_json()
    return str(output)


def _output_to_text(output: Any) -> str:
    """Extract human-readable text from any structured agent output for veto scanning.

    Section/PaperDraft outputs have well-known shapes; everything else falls
    back to the JSON dump used by the LLM rubric.
    """
    # Section-like
    if hasattr(output, "content") and isinstance(output.content, str):
        return output.content
    # PaperDraft-like
    if hasattr(output, "abstract") and hasattr(output, "sections"):
        parts = [getattr(output, "abstract", "")]
        parts.extend(getattr(s, "content", "") for s in getattr(output, "sections", []))
        return "\n\n".join(parts)
    return _output_to_json(output)
