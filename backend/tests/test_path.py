"""Tests for skoll.security.path.safe_resolve — THE workspace path guard."""

from __future__ import annotations

from pathlib import Path

import pytest
from skoll.errors import PathOutsideWorkspaceError
from skoll.security.path import safe_resolve


def test_allows_simple_relative_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    target = safe_resolve("src/auth.py", tmp_path)
    assert target == (tmp_path / "src" / "auth.py").resolve()
    assert target.is_relative_to(tmp_path.resolve())


def test_allows_nonexistent_path_within_workspace(tmp_path: Path) -> None:
    # write_file resolves before the file exists — must not require existence.
    target = safe_resolve("new/dir/file.txt", tmp_path)
    assert target.is_relative_to(tmp_path.resolve())


def test_allows_dot_current_dir_segments(tmp_path: Path) -> None:
    target = safe_resolve("./src/./auth.py", tmp_path)
    assert target == (tmp_path / "src" / "auth.py").resolve()


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("../secret.txt", tmp_path)


def test_rejects_deep_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("a/b/../../../etc/passwd", tmp_path)


def test_rejects_posix_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("/etc/passwd", tmp_path)


def test_rejects_windows_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve(r"C:\Windows\System32\drivers\etc\hosts", tmp_path)


def test_rejects_windows_drive_relative_path(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("C:foo.txt", tmp_path)


def test_rejects_backslash_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve(r"..\secret.txt", tmp_path)


def test_rejects_empty_and_whitespace_path(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("", tmp_path)
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("   ", tmp_path)


def test_rejects_symlink_escaping_workspace(tmp_path: Path) -> None:
    """A symlink inside the workspace that points outside it must be rejected."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret", encoding="utf-8")

    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/user")

    # Resolving through the symlink lands outside the workspace → rejected.
    with pytest.raises(PathOutsideWorkspaceError):
        safe_resolve("escape/secret.txt", workspace)


def test_accepts_string_or_path_workspace_root(tmp_path: Path) -> None:
    as_str = safe_resolve("f.txt", str(tmp_path))
    as_path = safe_resolve("f.txt", tmp_path)
    assert as_str == as_path
