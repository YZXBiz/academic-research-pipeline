"""Tests for the DeepSeek empty-assistant-message compatibility patch.

run-0511-2107 died on a DeepSeek 400:
  "Invalid assistant message: content or tool_calls must be set"

Root cause: pydantic_ai's OpenAIChatModel._into_message_param sets
`content = None` for any assistant turn with no TextPart and no
ToolCallPart (e.g. a thinking-only turn, where reasoning went to the
`reasoning_content` field). OpenAI tolerates `content: null`; DeepSeek's
stricter validator rejects it.

install_deepseek_message_patch wraps _map_model_response so that when the
mapped assistant message has `content is None` AND no `tool_calls`, the
content is coerced to an empty string — which satisfies DeepSeek's
"content or tool_calls must be set" rule without changing semantics.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIChatModel

from academic_pipeline.observability import install_deepseek_message_patch


def _model() -> OpenAIChatModel:
    """An OpenAIChatModel instance (no network calls in _map_model_response)."""
    return OpenAIChatModel("deepseek-v4-pro")


class TestDeepSeekMessagePatch:
    def test_empty_parts_response_gets_empty_string_content(self) -> None:
        """The exact buggy path: no text, no tool calls -> content was None."""
        install_deepseek_message_patch()
        model = _model()
        param = model._map_model_response(ModelResponse(parts=[]))
        assert param["role"] == "assistant"
        assert param.get("content") == ""  # coerced from None
        assert "tool_calls" not in param

    def test_text_response_content_is_unchanged(self) -> None:
        """A normal text turn must keep its real content untouched."""
        install_deepseek_message_patch()
        model = _model()
        param = model._map_model_response(
            ModelResponse(parts=[TextPart(content="The answer is 42.")])
        )
        assert param.get("content") == "The answer is 42."

    def test_tool_call_only_response_keeps_none_content(self) -> None:
        """A tool-call-only turn already satisfies 'content or tool_calls' —
        leave content as-is (None) so we don't mask a different bug class."""
        install_deepseek_message_patch()
        model = _model()
        param = model._map_model_response(
            ModelResponse(
                parts=[ToolCallPart(tool_name="search", args={"q": "x"}, tool_call_id="c1")]
            )
        )
        assert param.get("tool_calls")  # tool_calls present
        assert param.get("content") is None  # untouched — tool_calls satisfies the constraint

    def test_patch_is_idempotent(self) -> None:
        """Installing twice must not double-wrap."""
        install_deepseek_message_patch()
        once = OpenAIChatModel._map_model_response
        install_deepseek_message_patch()
        twice = OpenAIChatModel._map_model_response
        assert once is twice
