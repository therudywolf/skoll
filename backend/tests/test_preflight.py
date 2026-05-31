"""Tests for skoll.security.preflight.check_tool_call — the pre-tool-call gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skoll.agent.tools.registry import Tool, ToolContext, ToolSchema
from skoll.security.preflight import (
    PreflightResult,
    check_tool_call,
)


async def _noop_handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    return {}


def _read_tool() -> Tool:
    return Tool(
        schema=ToolSchema(
            name="read_file",
            description="read",
            phase="2",
            kind="read",
            requires_approval=False,
            auto_approve_default=True,
            path_args=["path"],
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            result_schema={"type": "object"},
        ),
        handler=_noop_handler,
    )


def _write_tool() -> Tool:
    return Tool(
        schema=ToolSchema(
            name="write_file",
            description="write",
            phase="2",
            kind="write",
            requires_approval=True,
            auto_approve_default=False,
            path_args=["path"],
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            result_schema={"type": "object"},
        ),
        handler=_noop_handler,
    )


def _shell_tool() -> Tool:
    return Tool(
        schema=ToolSchema(
            name="run_bash",
            description="exec",
            phase="2",
            kind="shell",
            requires_approval=True,
            auto_approve_default=False,
            path_args=[],
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
            result_schema={"type": "object"},
        ),
        handler=_noop_handler,
    )


class _FakeSession:
    def __init__(self, workspace_root: str, auto_approve: dict[str, bool] | None = None) -> None:
        self.workspace_root = workspace_root
        self.auto_approve = auto_approve or {}
        self.allowlist: object = None


async def test_bad_args_rejected(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_read_tool(), {"path": 123}, session)  # path not a string
    assert report.result is PreflightResult.REJECT
    assert report.rejection_reason is not None


async def test_missing_required_arg_rejected(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_read_tool(), {}, session)  # missing 'path'
    assert report.result is PreflightResult.REJECT


async def test_path_escape_rejected(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_read_tool(), {"path": "../../etc/passwd"}, session)
    assert report.result is PreflightResult.REJECT
    assert "passwd" in (report.rejection_reason or "") or "outside" in (
        report.rejection_reason or ""
    )


async def test_read_tool_auto_ok(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_read_tool(), {"path": "f.txt"}, session)
    assert report.result is PreflightResult.OK
    assert report.rejection_reason is None


async def test_write_tool_needs_approval(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_write_tool(), {"path": "out.txt", "content": "hi"}, session)
    assert report.result is PreflightResult.NEEDS_APPROVAL


async def test_write_tool_auto_approved_when_session_opts_in(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path), auto_approve={"write_file": True})
    report = await check_tool_call(_write_tool(), {"path": "out.txt", "content": "hi"}, session)
    assert report.result is PreflightResult.OK


async def test_exec_tool_needs_approval(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_shell_tool(), {"command": "ls -la"}, session)
    assert report.result is PreflightResult.NEEDS_APPROVAL


async def test_exec_tool_empty_command_rejected(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_shell_tool(), {"command": "   "}, session)
    assert report.result is PreflightResult.REJECT


async def test_exec_tool_nul_byte_rejected(tmp_path: Path) -> None:
    session = _FakeSession(str(tmp_path))
    report = await check_tool_call(_shell_tool(), {"command": "ls\x00rm"}, session)
    assert report.result is PreflightResult.REJECT


async def test_exec_tool_pipes_are_allowed_after_approval(tmp_path: Path) -> None:
    # Ordinary shell metacharacters are legitimate inside the sandbox.
    session = _FakeSession(str(tmp_path), auto_approve={"run_bash": True})
    report = await check_tool_call(
        _shell_tool(), {"command": "cat a.txt | grep foo && echo done"}, session
    )
    assert report.result is PreflightResult.OK


async def test_path_check_without_workspace_root_rejects(tmp_path: Path) -> None:
    session = _FakeSession("")  # no workspace root configured
    report = await check_tool_call(_read_tool(), {"path": "f.txt"}, session)
    assert report.result is PreflightResult.REJECT
