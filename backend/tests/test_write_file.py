"""Tests for the write_file tool (skoll.agent.tools.write_file)."""

from __future__ import annotations

from pathlib import Path

import pytest
from skoll.agent.tools.registry import ToolContext
from skoll.agent.tools.write_file import handler
from skoll.errors import PathOutsideWorkspaceError, ToolExecutionError


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="test-sess", workspace_root=str(tmp_path))


async def test_writes_new_file(tmp_path: Path) -> None:
    result = await handler(
        {"path": "out.txt", "content": "hello world", "reason": "test"}, _ctx(tmp_path)
    )
    assert result["created"] is True
    assert result["bytes_written"] == len(b"hello world")
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello world"


async def test_creates_parent_directories(tmp_path: Path) -> None:
    result = await handler(
        {"path": "a/b/c/deep.txt", "content": "x", "reason": "nested"}, _ctx(tmp_path)
    )
    assert result["created"] is True
    assert (tmp_path / "a" / "b" / "c" / "deep.txt").is_file()


async def test_overwrites_existing_file(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("old", encoding="utf-8")
    result = await handler(
        {"path": "f.txt", "content": "new content", "reason": "update"}, _ctx(tmp_path)
    )
    assert result["created"] is False
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "new content"


async def test_does_not_leave_temp_files(tmp_path: Path) -> None:
    await handler({"path": "f.txt", "content": "data", "reason": "r"}, _ctx(tmp_path))
    leftover = [p.name for p in tmp_path.iterdir() if p.name.startswith(".skoll-write-")]  # noqa: ASYNC240
    assert leftover == []


async def test_unicode_byte_count(tmp_path: Path) -> None:
    result = await handler({"path": "u.txt", "content": "héllo", "reason": "r"}, _ctx(tmp_path))
    assert result["bytes_written"] == len("héllo".encode())


async def test_path_escape_rejected(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        await handler({"path": "../escape.txt", "content": "x", "reason": "r"}, _ctx(tmp_path))


async def test_absolute_path_rejected(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        await handler({"path": "/etc/evil.txt", "content": "x", "reason": "r"}, _ctx(tmp_path))


async def test_directory_target_raises(tmp_path: Path) -> None:
    (tmp_path / "adir").mkdir()
    with pytest.raises(ToolExecutionError):
        await handler({"path": "adir", "content": "x", "reason": "r"}, _ctx(tmp_path))


async def test_non_string_content_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        await handler({"path": "f.txt", "content": 123, "reason": "r"}, _ctx(tmp_path))
