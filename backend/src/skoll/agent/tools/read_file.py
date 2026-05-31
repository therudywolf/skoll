"""read_file tool.

Issue: phase-2.1.
Schema: contracts/tools/read_file.json.

Read-only / auto-approve. Returns file content with secrets scrubbed and wrapped
as ``<untrusted_content>`` before it can reach the model's prompt (Golden Rules #4
and #5). The path is validated with :func:`~skoll.security.path.safe_resolve`
(Golden Rule #3) so a traversal attempt can never read outside the workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from skoll.errors import ToolExecutionError
from skoll.security.path import safe_resolve
from skoll.security.secrets import scrub
from skoll.security.untrusted import wrap

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext

# Hard ceiling on how many bytes we read from a single file before truncating, so a
# huge/binary file cannot blow up the prompt or backend memory. ``config.py`` has no
# dedicated setting for this (and is owned elsewhere), so it lives here as a module
# constant mirroring the sandbox's ``_MAX_OUTPUT_BYTES`` pattern.
_MAX_READ_BYTES: Final[int] = 1024 * 1024  # 1 MiB


def _read_text_capped(target: Path) -> tuple[str, bool]:
    """Read up to ``_MAX_READ_BYTES`` of ``target`` as UTF-8 (lenient).

    Returns ``(text, truncated_by_size)``. Decoding is lenient (``errors='replace'``)
    so a file with the odd non-UTF-8 byte still reads instead of raising.
    """
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ToolExecutionError(f"read_file: could not read {target.name!r}: {exc}") from exc

    truncated_by_size = len(raw) > _MAX_READ_BYTES
    if truncated_by_size:
        raw = raw[:_MAX_READ_BYTES]
    return raw.decode("utf-8", errors="replace"), truncated_by_size


def _slice_lines(text: str, start_line: int | None, end_line: int | None) -> tuple[str, bool]:
    """Apply an optional 1-indexed inclusive line slice.

    Returns ``(sliced_text, truncated_by_slice)``. Out-of-range bounds are clamped;
    ``start_line > end_line`` yields an empty slice. ``truncated_by_slice`` is True
    whenever the returned text omits any line of the original.
    """
    if start_line is None and end_line is None:
        return text, False

    lines = text.splitlines(keepends=True)
    total = len(lines)
    start_idx = max((start_line or 1) - 1, 0)
    end_idx = total if end_line is None else min(end_line, total)
    sliced = lines[start_idx:end_idx]
    truncated_by_slice = len(sliced) < total
    return "".join(sliced), truncated_by_slice


def _coerce_line_arg(args: dict[str, Any], key: str) -> int | None:
    """Read an optional 1-indexed line bound; tolerate absence, reject bad types."""
    raw = args.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolExecutionError(f"read_file: {key!r} must be an integer")
    if raw < 1:
        raise ToolExecutionError(f"read_file: {key!r} must be >= 1")
    return int(raw)


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Read a workspace file, scrub secrets, wrap untrusted, return per result_schema.

    args = {path: str, start_line?: int (>=1), end_line?: int (>=1)}

    Steps:
      1. ``safe_resolve(path, workspace_root)`` — reject traversal/escape.
      2. Read the file (UTF-8, capped at ``_MAX_READ_BYTES``).
      3. Optional 1-indexed inclusive line slice.
      4. ``secrets.scrub`` the (sliced) content.
      5. ``untrusted.wrap`` with ``source='file'`` + provenance.
      6. Return ``{path, content, lines_total, truncated, secrets_redacted}``.

    Raises:
        PathOutsideWorkspaceError: ``path`` escapes the workspace.
        ToolExecutionError: file missing/unreadable or bad line bounds.
    """
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolExecutionError("read_file: 'path' is required and must be a string")

    start_line = _coerce_line_arg(args, "start_line")
    end_line = _coerce_line_arg(args, "end_line")

    target = safe_resolve(raw_path, context.workspace_root)
    if not target.is_file():
        raise ToolExecutionError(f"read_file: not a file: {raw_path!r}")

    text, truncated_by_size = _read_text_capped(target)
    lines_total = len(text.splitlines())

    sliced, truncated_by_slice = _slice_lines(text, start_line, end_line)
    truncated = truncated_by_size or truncated_by_slice

    scrubbed, secrets_redacted = scrub(sliced)

    # Provenance for the untrusted wrapper: the line range actually returned.
    if start_line is not None or end_line is not None:
        lines_attr = f"{start_line or 1}-{end_line if end_line is not None else lines_total}"
    else:
        lines_attr = f"1-{lines_total}"

    content = wrap(
        scrubbed,
        source="file",
        path=raw_path,
        lines=lines_attr,
        secrets_redacted=secrets_redacted,
    )

    return {
        "path": raw_path,
        "content": content,
        "lines_total": lines_total,
        "truncated": truncated,
        "secrets_redacted": secrets_redacted,
    }
