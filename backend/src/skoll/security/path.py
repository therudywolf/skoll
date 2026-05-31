"""Workspace-relative path validation.

Issue: phase-1.* (used by every FS-touching tool).

This is THE path guard. Every tool that touches the filesystem resolves its
LLM-supplied path through :func:`safe_resolve` before doing any I/O. It enforces
Golden Rule #3 (``AGENTS.md`` §3.3): a path from the model is only valid if it
resolves to a location *inside* the workspace root.

The check is intentionally strict and layered:
  1. Reject absolute paths outright (an LLM passing ``/etc/passwd`` or ``C:\\Windows``
     must never be silently re-anchored under the workspace).
  2. Resolve the candidate against the (resolved) workspace root. ``Path.resolve``
     also collapses ``..`` segments and follows symlinks, so a symlink inside the
     workspace that points outside it is caught by the containment check below.
  3. Assert the resolved target ``is_relative_to`` the resolved workspace root.
  4. Defence-in-depth: reject any literal ``..`` segment in the user input even if
     step 3 would have caught it (cheap, and guards against future refactors).

Any violation raises :class:`~skoll.errors.PathOutsideWorkspaceError` (a
``PreflightError``); callers never see a bare ``ValueError``/``OSError`` for a
traversal attempt.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from skoll.errors import PathOutsideWorkspaceError


def _looks_absolute(user_path: str) -> bool:
    """True if ``user_path`` is absolute under POSIX *or* Windows semantics.

    The backend may run on Windows while the workspace contents are POSIX-style
    (e.g. agent-generated ``/etc/...`` paths), so we reject anything that is
    absolute under *either* OS rather than trusting the host's ``Path`` only.
    Drive-relative Windows paths (``C:foo``) and UNC roots are also treated as
    absolute / non-workspace-relative.
    """
    if PurePosixPath(user_path).is_absolute():
        return True
    win = PureWindowsPath(user_path)
    if win.is_absolute():
        return True
    # ``C:foo`` (drive-relative) — has a drive but is not "absolute"; still unsafe.
    return bool(win.drive)


def safe_resolve(user_path: str, workspace_root: str | Path) -> Path:
    """Resolve ``user_path`` against ``workspace_root``, rejecting any escape.

    Args:
        user_path: A workspace-relative path supplied by the model/user.
        workspace_root: The root the path must stay within.

    Returns:
        The absolute, resolved :class:`~pathlib.Path` inside the workspace.

    Raises:
        PathOutsideWorkspaceError: ``user_path`` is empty, absolute, contains a
            ``..`` segment, or otherwise resolves outside ``workspace_root``
            (including via a symlink pointing out of the tree).
    """
    if not user_path or not user_path.strip():
        raise PathOutsideWorkspaceError("empty path is not allowed")

    if _looks_absolute(user_path):
        raise PathOutsideWorkspaceError(
            f"absolute paths are not allowed: {user_path!r} (paths must be workspace-relative)"
        )

    # Defence-in-depth: reject explicit parent-dir segments before resolution.
    # Normalise separators so a Windows-style ``..\\`` is caught on every host.
    normalized = user_path.replace("\\", "/")
    if ".." in PurePosixPath(normalized).parts:
        raise PathOutsideWorkspaceError(f"path traversal ('..') is not allowed: {user_path!r}")

    root = Path(workspace_root).resolve()
    target = (root / normalized).resolve()

    if not target.is_relative_to(root):
        raise PathOutsideWorkspaceError(f"path {user_path!r} resolves outside the workspace root")

    return target
