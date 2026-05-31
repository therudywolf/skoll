"""Tests for the apply_diff tool (skoll.agent.tools.apply_diff)."""

from __future__ import annotations

from pathlib import Path

import pytest
from skoll.agent.tools.apply_diff import handler
from skoll.agent.tools.registry import ToolContext
from skoll.errors import PathOutsideWorkspaceError, ToolExecutionError


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(session_id="test-sess", workspace_root=str(tmp_path))


async def test_applies_single_block(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def fetch(url):\n    return get(url)\n", encoding="utf-8")
    result = await handler(
        {
            "path": "main.py",
            "reason": "rename",
            "blocks": [
                {
                    "search": "def fetch(url):\n",
                    "replace": "def fetch_json(url):\n",
                }
            ],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 1
    assert result["blocks_failed"] == 0
    assert (tmp_path / "main.py").read_text(encoding="utf-8").startswith("def fetch_json(url):")


async def test_sequential_blocks_see_earlier_replacements(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("A\nB\n", encoding="utf-8")
    result = await handler(
        {
            "path": "f.py",
            "reason": "chain",
            "blocks": [
                {"search": "A\n", "replace": "X\n"},
                {"search": "X\n", "replace": "Z\n"},  # only matches after block 1
            ],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 2
    assert (tmp_path / "f.py").read_text(encoding="utf-8") == "Z\nB\n"


async def test_fuzzy_whitespace_match(tmp_path: Path) -> None:
    # File uses 4-space indent + trailing spaces; search uses different whitespace.
    (tmp_path / "ws.py").write_text("def f():\n    x  =  1   \n    return x\n", encoding="utf-8")
    result = await handler(
        {
            "path": "ws.py",
            "reason": "fuzzy",
            "blocks": [
                {"search": "    x = 1\n", "replace": "    x = 2\n"},
            ],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 1
    assert result["blocks_failed"] == 0
    assert "x = 2" in (tmp_path / "ws.py").read_text(encoding="utf-8")


async def test_no_match_returns_structured_error(tmp_path: Path) -> None:
    original = "hello world\n"
    (tmp_path / "f.txt").write_text(original, encoding="utf-8")
    result = await handler(
        {
            "path": "f.txt",
            "reason": "miss",
            "blocks": [{"search": "nonexistent text\n", "replace": "x\n"}],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 0
    assert result["blocks_failed"] == 1
    assert result["failures"][0]["block_index"] == 0
    assert result["failures"][0]["reason"] == "search_not_found"
    # All-or-nothing: file unchanged.
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == original


async def test_ambiguous_match_returns_structured_error(tmp_path: Path) -> None:
    original = "dup\ndup\n"
    (tmp_path / "f.txt").write_text(original, encoding="utf-8")
    result = await handler(
        {
            "path": "f.txt",
            "reason": "ambig",
            "blocks": [{"search": "dup\n", "replace": "x\n"}],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_failed"] == 1
    assert result["failures"][0]["reason"] == "search_ambiguous"
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == original


async def test_all_or_nothing_one_block_fails(tmp_path: Path) -> None:
    original = "keep\nchange-me\n"
    (tmp_path / "f.txt").write_text(original, encoding="utf-8")
    result = await handler(
        {
            "path": "f.txt",
            "reason": "partial",
            "blocks": [
                {"search": "change-me\n", "replace": "changed\n"},  # would succeed
                {"search": "absent\n", "replace": "y\n"},  # fails
            ],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 0
    assert result["blocks_failed"] == 1
    # Nothing written because a sibling block failed.
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == original


async def test_delete_via_empty_replace(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("keep\ndelete this\nkeep2\n", encoding="utf-8")
    result = await handler(
        {
            "path": "f.txt",
            "reason": "delete",
            "blocks": [{"search": "delete this\n", "replace": ""}],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_applied"] == 1
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "keep\nkeep2\n"


async def test_whitespace_only_search_is_not_found(tmp_path: Path) -> None:
    original = "a\n    \nb\n"
    (tmp_path / "f.txt").write_text(original, encoding="utf-8")
    result = await handler(
        {
            "path": "f.txt",
            "reason": "ws-only",
            "blocks": [{"search": "    ", "replace": "x"}],
        },
        _ctx(tmp_path),
    )
    assert result["blocks_failed"] == 1
    assert result["failures"][0]["reason"] == "search_not_found"
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == original


async def test_path_escape_raises(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        await handler(
            {
                "path": "../evil.txt",
                "reason": "r",
                "blocks": [{"search": "a", "replace": "b"}],
            },
            _ctx(tmp_path),
        )


async def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        await handler(
            {
                "path": "nope.txt",
                "reason": "r",
                "blocks": [{"search": "a", "replace": "b"}],
            },
            _ctx(tmp_path),
        )


async def test_empty_blocks_raises(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ToolExecutionError):
        await handler({"path": "f.txt", "reason": "r", "blocks": []}, _ctx(tmp_path))
