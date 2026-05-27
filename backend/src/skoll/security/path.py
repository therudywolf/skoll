"""Workspace-relative path validation.

Issue: phase-1.* (used by every FS-touching tool).
"""

from __future__ import annotations

from pathlib import Path

from skoll.errors import PathOutsideWorkspaceError


def safe_resolve(user_path: str, workspace_root: str | Path) -> Path:
    """Resolve a user-supplied path against workspace_root.

    Raises PathOutsideWorkspaceError if the resolved path escapes workspace_root.

    Implementation:
      1. workspace_root = Path(workspace_root).resolve()
      2. target = (workspace_root / user_path).resolve()
      3. assert target.is_relative_to(workspace_root)
      4. assert not any segment is '..' (defense-in-depth even though step 3 catches it)
      5. return target
    """
    # TODO(phase-1)
    raise NotImplementedError
