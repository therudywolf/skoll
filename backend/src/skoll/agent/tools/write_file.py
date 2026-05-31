"""write_file tool. REQUIRES APPROVAL.

Issue: phase-2.2.
Schema: contracts/tools/write_file.json.

Approval is the agent loop's / preflight's job: by the time ``handler`` runs the
user (or an explicit per-session auto-approve) has already consented, so this
module just writes — it does NOT prompt. The path is validated with
:func:`~skoll.security.path.safe_resolve`, so content can never be written
outside the workspace, and parent directories are created only *within* it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skoll.errors import ToolExecutionError
from skoll.security.path import safe_resolve

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext


def _atomic_write(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` atomically (temp file in the same dir + rename).

    Writing into the same directory keeps the rename on one filesystem (so it is
    atomic) and inside the workspace (the temp file never lands outside the
    validated tree). ``os.replace`` overwrites an existing file atomically.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".skoll-write-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise ToolExecutionError(f"write_file: could not write {target.name!r}: {exc}") from exc


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Create or overwrite a workspace file, return per result_schema.

    args = {path: str, content: str, reason: str}

    Steps:
      1. ``safe_resolve(path, workspace_root)`` — reject traversal/escape.
      2. Atomic write (temp file in the target's dir + ``os.replace``); parent
         dirs created within the workspace.
      3. Return ``{path, bytes_written, created}`` (``created`` = file was new).

    Raises:
        PathOutsideWorkspaceError: ``path`` escapes the workspace.
        ToolExecutionError: ``content`` is not a string or the write failed.
    """
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolExecutionError("write_file: 'path' is required and must be a string")

    content = args.get("content")
    if not isinstance(content, str):
        raise ToolExecutionError("write_file: 'content' is required and must be a string")

    target = safe_resolve(raw_path, context.workspace_root)
    if target.is_dir():
        raise ToolExecutionError(f"write_file: path is a directory: {raw_path!r}")

    created = not target.exists()
    data = content.encode("utf-8")
    _atomic_write(target, data)

    return {
        "path": raw_path,
        "bytes_written": len(data),
        "created": created,
    }
