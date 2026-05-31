"""Tests for the read_file tool (skoll.agent.tools.read_file)."""

from __future__ import annotations

from pathlib import Path

import pytest
from skoll.agent.tools.read_file import _MAX_READ_BYTES, handler
from skoll.agent.tools.registry import ToolContext
from skoll.errors import PathOutsideWorkspaceError, ToolExecutionError


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="test-sess", workspace_root=str(tmp_path))


async def test_reads_workspace_file(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    result = await handler({"path": "hello.txt"}, _ctx(tmp_path))

    assert result["path"] == "hello.txt"
    assert result["lines_total"] == 3
    assert result["truncated"] is False
    assert result["secrets_redacted"] == 0
    # Content is wrapped as untrusted with provenance.
    assert "<untrusted_content" in result["content"]
    assert 'source="file"' in result["content"]
    assert "line2" in result["content"]


async def test_scrubs_planted_secret(tmp_path: Path) -> None:
    # Fake AWS access key matching the gitleaks `aws-access-token` default rule.
    fake_secret = "AKIAABCDEFGH234567ZZ"  # noqa: S105 - fake AWS key fixture (gitleaks:allow)
    (tmp_path / "config.py").write_text(f'AWS_KEY = "{fake_secret}"\n', encoding="utf-8")
    result = await handler({"path": "config.py"}, _ctx(tmp_path))

    assert result["secrets_redacted"] >= 1
    assert fake_secret not in result["content"]
    assert "[REDACTED:aws-access-token]" in result["content"]
    # And the redaction count is reflected in the untrusted wrapper metadata.
    assert 'secrets_redacted="1"' in result["content"]


async def test_line_slicing(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_bytes(b"a\nb\nc\nd\ne\n")
    result = await handler({"path": "many.txt", "start_line": 2, "end_line": 4}, _ctx(tmp_path))

    assert result["lines_total"] == 5  # total is the whole file
    assert result["truncated"] is True  # we returned a slice
    assert "b\nc\nd" in result["content"]
    assert "\na\n" not in result["content"]
    assert 'lines="2-4"' in result["content"]


async def test_path_escape_raises(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        await handler({"path": "../../etc/passwd"}, _ctx(tmp_path))


async def test_missing_file_raises_tool_error(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        await handler({"path": "does_not_exist.txt"}, _ctx(tmp_path))


async def test_directory_path_raises(tmp_path: Path) -> None:
    (tmp_path / "adir").mkdir()
    with pytest.raises(ToolExecutionError):
        await handler({"path": "adir"}, _ctx(tmp_path))


async def test_oversize_file_is_truncated(tmp_path: Path) -> None:
    big = "x" * (_MAX_READ_BYTES + 1000)
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    result = await handler({"path": "big.txt"}, _ctx(tmp_path))
    assert result["truncated"] is True
