"""Tests for the run_bash tool (skoll.agent.tools.run_bash).

The sandbox is fully mocked here (no Docker). A real-Docker round-trip lives in
tests/test_sandbox.py under ``@pytest.mark.integration``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import skoll.agent.tools.run_bash as run_bash_mod
from skoll.agent.tools.registry import ToolContext
from skoll.agent.tools.run_bash import (
    _MAX_STREAM_CHARS,
    _default_sandbox_provider,
    handler,
    set_sandbox_provider,
)
from skoll.errors import SandboxStartError, ToolExecutionError
from skoll.sandbox.session import BashResult


@pytest.fixture(autouse=True)
def _restore_provider() -> Iterator[None]:
    """Reset the module-level provider seam after every test."""
    original = run_bash_mod._sandbox_provider
    try:
        yield
    finally:
        run_bash_mod._sandbox_provider = original


class _FakeSandbox:
    """Records the last run_bash call and returns a canned BashResult."""

    def __init__(self, result: BashResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def run_bash(
        self,
        command: str,
        *,
        working_directory: str = ".",
        timeout_seconds: int | None = None,
    ) -> BashResult:
        self.calls.append(
            {
                "command": command,
                "working_directory": working_directory,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self._result


def _ctx() -> ToolContext:
    return ToolContext(session_id="sess-1", workspace_root="/workspace")


async def test_default_provider_raises_when_unwired() -> None:
    with pytest.raises(SandboxStartError):
        await _default_sandbox_provider(_ctx())


async def test_returns_expected_shape() -> None:
    fake = _FakeSandbox(
        BashResult(exit_code=0, stdout="hello\n", stderr="", duration_ms=42, timed_out=False)
    )
    set_sandbox_provider(lambda _ctx: fake)

    result = await handler({"command": "echo hello", "reason": "test"}, _ctx())

    assert result == {
        "exit_code": 0,
        "stdout": "hello\n",
        "stderr": "",
        "duration_ms": 42,
        "timed_out": False,
    }
    # working_directory defaults to '.', timeout passthrough is None (sandbox default).
    assert fake.calls[0]["working_directory"] == "."
    assert fake.calls[0]["timeout_seconds"] is None


async def test_async_provider_is_awaited() -> None:
    fake = _FakeSandbox(
        BashResult(exit_code=1, stdout="", stderr="boom", duration_ms=10, timed_out=False)
    )

    async def _provider(_ctx: ToolContext) -> _FakeSandbox:
        return fake

    set_sandbox_provider(_provider)
    result = await handler({"command": "false", "reason": "r"}, _ctx())
    assert result["exit_code"] == 1
    assert result["stderr"] == "boom"


async def test_passes_working_directory_and_timeout() -> None:
    fake = _FakeSandbox(
        BashResult(exit_code=0, stdout="", stderr="", duration_ms=1, timed_out=False)
    )
    set_sandbox_provider(lambda _ctx: fake)

    await handler(
        {
            "command": "pytest",
            "working_directory": "backend",
            "timeout_seconds": 120,
            "reason": "run tests",
        },
        _ctx(),
    )
    assert fake.calls[0]["working_directory"] == "backend"
    assert fake.calls[0]["timeout_seconds"] == 120


async def test_timeout_clamped_to_contract_max() -> None:
    fake = _FakeSandbox(
        BashResult(exit_code=0, stdout="", stderr="", duration_ms=1, timed_out=False)
    )
    set_sandbox_provider(lambda _ctx: fake)

    await handler({"command": "x", "timeout_seconds": 99999, "reason": "r"}, _ctx())
    assert fake.calls[0]["timeout_seconds"] == 300  # clamped to contract maximum


async def test_timed_out_result_propagated() -> None:
    fake = _FakeSandbox(
        BashResult(
            exit_code=124,
            stdout="",
            stderr="command timed out after 30s",
            duration_ms=30000,
            timed_out=True,
        )
    )
    set_sandbox_provider(lambda _ctx: fake)

    result = await handler({"command": "sleep 999", "reason": "r"}, _ctx())
    assert result["timed_out"] is True
    assert result["exit_code"] == 124


async def test_long_output_truncated() -> None:
    long_out = "x" * (_MAX_STREAM_CHARS + 5000)
    fake = _FakeSandbox(
        BashResult(exit_code=0, stdout=long_out, stderr="", duration_ms=5, timed_out=False)
    )
    set_sandbox_provider(lambda _ctx: fake)

    result = await handler({"command": "yes", "reason": "r"}, _ctx())
    assert len(result["stdout"]) < len(long_out)
    assert "output truncated" in result["stdout"]


async def test_empty_command_raises() -> None:
    with pytest.raises(ToolExecutionError):
        await handler({"command": "   ", "reason": "r"}, _ctx())


async def test_unwired_handler_raises_sandbox_error() -> None:
    # Provider left at its default (autouse fixture restores it afterwards).
    with pytest.raises(SandboxStartError):
        await handler({"command": "echo hi", "reason": "r"}, _ctx())


async def test_bad_timeout_type_raises() -> None:
    fake = _FakeSandbox(
        BashResult(exit_code=0, stdout="", stderr="", duration_ms=1, timed_out=False)
    )
    set_sandbox_provider(lambda _ctx: fake)
    with pytest.raises(ToolExecutionError):
        await handler({"command": "x", "timeout_seconds": "30", "reason": "r"}, _ctx())
