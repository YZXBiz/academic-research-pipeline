"""Tests for copilot_checkpoint."""

from __future__ import annotations

import pytest

from academic_pipeline.traceability.copilot import copilot_checkpoint


@pytest.mark.asyncio
async def test_copilot_disabled_returns_none() -> None:
    result = await copilot_checkpoint(
        name="test", summary="something", timeout_s=1, enabled=False,
        stdin_reader=lambda timeout: "should not be called",  # type: ignore[arg-type]
    )
    assert result is None


@pytest.mark.asyncio
async def test_copilot_enabled_returns_user_input() -> None:
    async def fake_reader(timeout: float) -> str:
        return "fix the methodology"
    result = await copilot_checkpoint(
        name="test", summary="check", timeout_s=1, enabled=True, stdin_reader=fake_reader,
    )
    assert result == "fix the methodology"


@pytest.mark.asyncio
async def test_copilot_timeout_returns_none() -> None:
    async def fake_reader(timeout: float) -> str:
        raise TimeoutError("simulated timeout")
    result = await copilot_checkpoint(
        name="test", summary="check", timeout_s=1, enabled=True, stdin_reader=fake_reader,
    )
    assert result is None


@pytest.mark.asyncio
async def test_copilot_empty_input_returns_none() -> None:
    async def fake_reader(timeout: float) -> str:
        return "   "  # whitespace only
    result = await copilot_checkpoint(
        name="test", summary="check", timeout_s=1, enabled=True, stdin_reader=fake_reader,
    )
    assert result is None


@pytest.mark.asyncio
async def test_copilot_strips_whitespace_from_input() -> None:
    async def fake_reader(timeout: float) -> str:
        return "  add a sentence about CKD  \n"
    result = await copilot_checkpoint(
        name="test", summary="check", timeout_s=1, enabled=True, stdin_reader=fake_reader,
    )
    assert result == "add a sentence about CKD"
