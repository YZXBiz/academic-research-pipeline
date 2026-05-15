"""Save full agent traces (prompts, responses, tool calls, tokens) to disk."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path  # noqa: TCH003 — runtime use in TraceLogger.__init__ signature
from typing import TYPE_CHECKING, Any

from pydantic_ai import AgentRunResult  # noqa: TCH002 — runtime use in TraceLogger.log signature


if TYPE_CHECKING:
    from academic_pipeline.core.deps import PipelineDeps
    from academic_pipeline.models.shared import EvaluationResult

logger = logging.getLogger(__name__)

_MAX_TOOL_RESULT_CHARS = 3000
_AGENT_RUN_TIMEOUT_S = 1800.0
# 15-minute wall-clock cap per agent.run. Must be LESS than recovery/watchdog.py
# max_idle_s (1200s) so wedged calls raise AgentTimeoutError → the snapshot is
# recorded as 'error' → auto-resume picks up cleanly.
# Bumped from 480s (the proxied-Anthropic-SSE-wedge-tuned value) after
# run-0511-2107 post-mortem: integrity_verification_agent legitimately needs
# 500-700s on DeepSeek-v4-pro for multi-tool Exa+claim-verification work. The
# 1200s watchdog cap retains room for 3-strikes escalation to fire on truly
# wedged LLM proxy-class hangs (multi-hour).


def _is_json(text: str) -> bool:
    """Check if text is valid JSON."""
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def _render_json_as_markdown(text: str) -> str:
    """Render JSON as human-readable markdown with labels, lists, and indentation."""
    try:
        parsed = json.loads(text)
        return _json_to_md(parsed, depth=0)
    except (json.JSONDecodeError, TypeError):
        return text


def _json_to_md(obj: Any, depth: int = 0) -> str:
    """Recursively convert a JSON value to readable markdown."""
    if isinstance(obj, dict):
        lines: list[str] = []
        for key, val in obj.items():
            label = key.replace("_", " ").title()
            if isinstance(val, str) and len(val) > 120:
                lines.append(f"\n**{label}:**\n{val}\n")
            elif isinstance(val, str):
                lines.append(f"**{label}:** {val}")
            elif isinstance(val, bool):
                lines.append(f"**{label}:** {'Yes' if val else 'No'}")
            elif isinstance(val, int | float):
                lines.append(f"**{label}:** {val}")
            elif val is None:
                lines.append(f"**{label}:** —")
            elif isinstance(val, list):
                lines.append(f"\n**{label}:**")
                for i, item in enumerate(val, 1):
                    if isinstance(item, str):
                        lines.append(f"  {i}. {item}")
                    elif isinstance(item, dict):
                        inner = _json_to_md(item, depth + 1)
                        indented = "\n".join("    " + line for line in inner.split("\n") if line.strip())
                        lines.append(f"  {i}.\n{indented}")
                    else:
                        lines.append(f"  {i}. {item}")
            elif isinstance(val, dict):
                inner = _json_to_md(val, depth + 1)
                lines.append(f"\n**{label}:**\n{inner}")
            else:
                lines.append(f"**{label}:** {val}")
        return "\n".join(lines)
    if isinstance(obj, list):
        return "\n".join(f"- {_json_to_md(item, depth + 1)}" for item in obj)
    return str(obj)


class TraceLogger:
    """Writes per-agent trace files to output/<run_id>/<phase>/traces/."""

    def __init__(self, output_dir: Path) -> None:
        """Bind the trace output dir for this run."""
        self.output_dir = output_dir
        self._sequence: dict[str, int] = {}

    def _next_seq(self, phase: str) -> int:
        """Return the next sequence number for a phase."""
        count = self._sequence.get(phase, 0) + 1
        self._sequence[phase] = count
        return count

    def log(
        self,
        name: str,
        phase: str,
        result: AgentRunResult[Any],
        eval_result: EvaluationResult | None = None,
    ) -> None:
        """Save a single agent run as readable markdown + raw JSON."""
        try:
            usage = result.usage()
            try:
                raw_messages = json.loads(result.all_messages_json().decode())
            except Exception:
                try:
                    raw_messages = json.loads(json.dumps([m.model_dump() for m in result.all_messages()], default=str))
                except Exception as e:
                    logger.warning("Message serialization failed for %s/%s: %s", phase, name, e)
                    raw_messages = [
                        {"parts": [{"part_kind": "system-prompt", "content": f"[messages unavailable: {e}]"}]}
                    ]
            timestamp = datetime.now(UTC).isoformat()
            seq = self._next_seq(phase)

            raw_data = {
                "agent": name,
                "phase": phase,
                "sequence": seq,
                "timestamp": timestamp,
                "usage": {
                    "input_tokens": usage.request_tokens or 0,
                    "output_tokens": usage.response_tokens or 0,
                    "requests": usage.requests,
                },
                "messages": raw_messages,
            }
            if eval_result:
                per_model = getattr(eval_result, "per_model", [])
                raw_data["evaluation"] = {
                    "verdict": eval_result.verdict,
                    "scores": dict(eval_result.scores),
                    "feedback": eval_result.feedback,
                    "weakest_dimension": eval_result.weakest_dimension,
                    "per_model": [
                        {"model": m.model_name, "scores": dict(m.scores), "feedback": m.feedback} for m in per_model
                    ]
                    if per_model
                    else [],
                }

            trace_dir = self.output_dir / phase / "traces"
            raw_dir = trace_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)

            prefix = f"{seq:02d}"
            (raw_dir / f"{prefix}_{name}.json").write_text(
                json.dumps(raw_data, indent=2, default=str), encoding="utf-8"
            )

            trace_dir.mkdir(parents=True, exist_ok=True)
            (trace_dir / f"{prefix}_{name}.md").write_text(
                _format_readable(name, raw_data, eval_result), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to save trace for %s/%s", phase, name)


def _format_readable(
    name: str,
    data: dict[str, Any],
    eval_result: EvaluationResult | None,
) -> str:
    usage = data["usage"]
    seq = data.get("sequence", "?")
    lines = [
        f"# {name}",
        (
            f"Step {seq} in {data.get('phase', '?')} | "
            f"Tokens: {usage['input_tokens']:,} in / {usage['output_tokens']:,} out | "
            f"Requests: {usage['requests']}"
        ),
        f"Timestamp: {data['timestamp']}",
        "",
    ]

    request_num = 0
    for msg in data["messages"]:
        parts = msg.get("parts", [])
        for part in parts:
            pt = part.get("part_kind", part.get("type", ""))

            if pt == "system-prompt":
                lines.extend(["## System Prompt", "", part.get("content", ""), ""])

            elif pt == "user-prompt":
                request_num += 1
                content = part.get("content", "")
                header = "User Message" if request_num == 1 else f"User Message (request {request_num})"
                if isinstance(content, str):
                    lines.extend([f"## {header}", "", content, ""])
                else:
                    lines.extend([f"## {header}", "", json.dumps(content, indent=2, default=str), ""])

            elif pt == "retry-prompt":
                request_num += 1
                content = part.get("content", "")
                if isinstance(content, str):
                    lines.extend([f"## Retry (request {request_num})", "", content, ""])
                else:
                    lines.extend(
                        [f"## Retry (request {request_num})", "", json.dumps(content, indent=2, default=str), ""]
                    )

            elif pt == "thinking":
                content = part.get("content", "")
                if content:
                    header = "Thinking" if request_num <= 1 else f"Thinking (request {request_num})"
                    lines.extend([f"## {header}", "", content[:2000], ""])

            elif pt == "text":
                content = part.get("content", "")
                # Strip markdown code fences before JSON check
                stripped = content.strip()
                if stripped.startswith("```json"):
                    stripped = stripped[len("```json") :].strip()
                if stripped.startswith("```"):
                    stripped = stripped[3:].strip()
                if stripped.endswith("```"):
                    stripped = stripped[:-3].strip()
                header = "Model Response" if request_num <= 1 else f"Model Response (request {request_num})"
                lines.append(f"## {header}")
                lines.append("")
                if _is_json(stripped):
                    lines.extend([_render_json_as_markdown(stripped), ""])
                else:
                    lines.extend([content, ""])

            elif pt == "tool-call":
                tool_name = part.get("tool_name", "unknown")
                args = part.get("args", {})
                args_str = args if isinstance(args, str) else json.dumps(args, indent=2, default=str)
                lines.extend(
                    [
                        f"### Tool Call: {tool_name}",
                        "",
                        f"```json\n{args_str}\n```",
                        "",
                    ]
                )

            elif pt == "tool-return":
                tool_name = part.get("tool_name", "unknown")
                content = str(part.get("content", ""))
                if len(content) > _MAX_TOOL_RESULT_CHARS:
                    content = content[:_MAX_TOOL_RESULT_CHARS] + "\n... [truncated]"
                lines.extend(
                    [
                        f"### Tool Result: {tool_name}",
                        "",
                        f"```\n{content}\n```",
                        "",
                    ]
                )

    if eval_result:
        lines.extend(
            [
                "## Evaluation",
                "",
                f"**Verdict:** {eval_result.verdict}",
            ]
        )
        if eval_result.scores:
            lines.append("")
            lines.append("| Dimension | Score |")
            lines.append("|-----------|-------|")
            for k, v in eval_result.scores.items():
                lines.append(f"| {k} | {v} |")
        if eval_result.weakest_dimension:
            lines.append("")
            lines.append(f"**Weakest dimension:** {eval_result.weakest_dimension}")
        if eval_result.feedback:
            lines.append("")
            lines.append("**Feedback:**")
            lines.append("")
            for part in eval_result.feedback.split(" | "):
                part = part.strip()
                if part.startswith("["):
                    bracket_end = part.find("]")
                    if bracket_end > 0:
                        model_tag = part[: bracket_end + 1]
                        feedback_text = part[bracket_end + 1 :].strip()
                        lines.append(f"- {model_tag} {feedback_text}")
                        lines.append("")
                    else:
                        lines.append(f"- {part}")
                        lines.append("")
                else:
                    lines.append(f"- {part}")
                    lines.append("")
        per_model = getattr(eval_result, "per_model", [])
        if per_model:
            lines.append("### Per-Model Scores")
            lines.append("")
            dims = sorted({d for m in per_model for d in m.scores})
            header = "| Dimension | " + " | ".join(m.model_name for m in per_model) + " | Median |"
            sep = "|-----------|" + "|".join("----:" for _ in per_model) + "|-------:|"
            lines.append(header)
            lines.append(sep)
            for dim in dims:
                row = f"| {dim} "
                for m in per_model:
                    row += f"| {m.scores.get(dim, '-')} "
                row += f"| {eval_result.scores.get(dim, '-')} |"
                lines.append(row)
            lines.append("")
        lines.append("")

    return "\n".join(lines)


# Module-level set of agent ids already wired through logfire.instrument_pydantic_ai().
# Idempotency guard for PRD §6.13.T3: instrumenting the same agent twice would
# double-emit spans. Keyed by id() because Agent instances are not hashable
# in all cases and we only need identity comparison within a single process.
_instrumented_agents: set[int] = set()


def _instrument_agent_once(agent: Any) -> None:
    """Per-agent logfire instrumentation (PRD §6.13.T3) — idempotent.

    Adds the agent's name attribute as a span tag so reviewers can filter
    Logfire queries by agent. No-op if logfire is unavailable; failures
    are logged at debug level so an observability gap never breaks the
    pipeline.
    """
    if id(agent) in _instrumented_agents:
        return
    try:
        import logfire

        logfire.instrument_pydantic_ai(agent)
        _instrumented_agents.add(id(agent))
    except Exception as exc:
        # Observability must never raise. Logfire being absent or
        # unconfigured (e.g. in tests) is fine; downgrade to debug.
        logger.debug("Per-agent logfire instrumentation skipped: %s", exc)


async def traced_agent_run(
    agent: Any,
    context: str,
    *,
    deps: PipelineDeps,
    name: str,
    phase: str,
    eval_result: EvaluationResult | None = None,
    **kwargs: Any,
) -> AgentRunResult[Any]:
    """Run an agent and save the full conversation trace to disk."""
    from academic_pipeline.recovery.bounded_run import bounded_agent_run

    _instrument_agent_once(agent)
    result = await bounded_agent_run(agent, context, deps=deps, timeout_s=_AGENT_RUN_TIMEOUT_S, **kwargs)
    if deps.trace_logger:
        deps.trace_logger.log(name, phase, result, eval_result)
    return result
