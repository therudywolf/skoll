"""apply_diff tool — SEARCH/REPLACE format. REQUIRES APPROVAL.

Issue: phase-2.3.
Schema: contracts/tools/apply_diff.json.
Format spec: prompts/edit_format.md.

Implementation notes:
  - Apply blocks SEQUENTIALLY; later blocks see earlier blocks' replacements
    (we mutate an in-memory copy of the file as we go).
  - For each block: the ``search`` text must appear EXACTLY once in the current
    working copy → otherwise ``search_ambiguous`` (>1) or ``search_not_found`` (0).
  - Whitespace-only ``search`` is rejected as ``search_not_found`` (ambiguous by spec).
  - ATOMIC: if ANY block fails we do NOT write — we collect every failure, return
    them, and leave the file unchanged (``blocks_applied`` reflects the dry run as 0).
  - Fuzzy fallback (Aider-style): if the exact ``search`` is not found, retry with a
    whitespace-normalised, line-based match; on a unique fuzzy hit we log a warning
    and proceed. Ambiguity is still a failure.
  - No-match is a STRUCTURED result (per result_schema), never a raised exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import structlog

from skoll.errors import ToolExecutionError
from skoll.security.path import safe_resolve

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext

logger = structlog.get_logger(__name__)

_NOT_FOUND = "search_not_found"
_AMBIGUOUS = "search_ambiguous"


def _normalize_ws(text: str) -> str:
    """Collapse a line's internal whitespace and strip its ends.

    Used only for the fuzzy fallback so that pure-whitespace differences (re-indents,
    trailing spaces, tabs↔spaces) still match. Line *structure* is preserved: we
    normalise per line and rejoin with ``\\n`` so a multi-line search keeps its shape.
    """
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


def _count_exact(haystack: str, needle: str) -> int:
    """Number of non-overlapping occurrences of ``needle`` in ``haystack``."""
    if not needle:
        return 0
    return haystack.count(needle)


def _fuzzy_find_unique(haystack: str, needle: str) -> tuple[int, int] | Literal["ambiguous"] | None:
    """Find a unique whitespace-normalised match of ``needle`` in ``haystack``.

    Returns:
        (start, end) char offsets into ``haystack`` for a single fuzzy match,
        the string ``"ambiguous"`` if more than one normalised window matches,
        or ``None`` if none match.

    Matching is line-window based: we slide a window of ``len(needle_lines)`` lines
    over ``haystack`` and compare the normalised window to the normalised needle.
    """
    needle_norm = _normalize_ws(needle)
    if not needle_norm.strip():
        return None

    hay_lines = haystack.splitlines(keepends=True)
    needle_line_count = len(needle.splitlines()) or 1

    # Precompute char offsets at each line start for slice reconstruction.
    offsets: list[int] = []
    running = 0
    for line in hay_lines:
        offsets.append(running)
        running += len(line)
    offsets.append(running)  # sentinel == len(haystack)

    matches: list[tuple[int, int]] = []
    for i in range(0, max(len(hay_lines) - needle_line_count + 1, 0)):
        window = "".join(hay_lines[i : i + needle_line_count])
        if _normalize_ws(window) == needle_norm:
            start = offsets[i]
            end = offsets[i + needle_line_count]
            matches.append((start, end))

    if len(matches) > 1:
        return "ambiguous"
    if len(matches) == 1:
        return matches[0]
    return None


def _apply_block(
    working: str, search: str, replace: str, *, block_index: int
) -> tuple[str, str | None]:
    """Apply one SEARCH/REPLACE block to ``working``.

    Returns ``(new_working, failure_reason)``. ``failure_reason`` is ``None`` on
    success, else ``_NOT_FOUND`` / ``_AMBIGUOUS``. On failure ``working`` is
    returned unchanged.
    """
    # Whitespace-only search is ambiguous by spec → treat as not-found.
    if not search.strip():
        return working, _NOT_FOUND

    exact = _count_exact(working, search)
    if exact == 1:
        return working.replace(search, replace, 1), None
    if exact > 1:
        return working, _AMBIGUOUS

    # Exact miss → fuzzy whitespace-tolerant fallback.
    fuzzy = _fuzzy_find_unique(working, search)
    if fuzzy is None:
        return working, _NOT_FOUND
    if fuzzy == "ambiguous":
        return working, _AMBIGUOUS

    start, end = fuzzy
    logger.warning("skoll.apply_diff.fuzzy_match", block_index=block_index)
    return working[:start] + replace + working[end:], None


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Apply SEARCH/REPLACE blocks to a workspace file (all-or-nothing).

    args = {path: str, blocks: [{search: str, replace: str}, ...], reason: str}

    Steps:
      1. ``safe_resolve(path, workspace_root)`` — reject traversal/escape.
      2. Read the current file content.
      3. Apply each block in order to an in-memory copy (exact-then-fuzzy match).
      4. If every block applied, write the result atomically; otherwise leave the
         file unchanged and report the failures.

    Returns ``{path, blocks_applied, blocks_failed, failures: [{block_index, reason}]}``
    where ``reason`` ∈ {``search_not_found``, ``search_ambiguous``}. A no-match is a
    structured result, NOT a raised exception.

    Raises:
        PathOutsideWorkspaceError: ``path`` escapes the workspace.
        ToolExecutionError: ``blocks`` malformed, or the file is missing/unreadable.
    """
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolExecutionError("apply_diff: 'path' is required and must be a string")

    blocks = args.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ToolExecutionError("apply_diff: 'blocks' is required and must be a non-empty list")

    target = safe_resolve(raw_path, context.workspace_root)
    if not target.is_file():
        raise ToolExecutionError(f"apply_diff: not a file: {raw_path!r}")

    try:
        original = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolExecutionError(f"apply_diff: could not read {raw_path!r}: {exc}") from exc

    working = original
    failures: list[dict[str, Any]] = []
    applied = 0

    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ToolExecutionError(f"apply_diff: block {index} must be an object")
        search = block.get("search")
        replace = block.get("replace")
        if not isinstance(search, str) or not isinstance(replace, str):
            raise ToolExecutionError(
                f"apply_diff: block {index} must have string 'search' and 'replace'"
            )

        working, reason = _apply_block(working, search, replace, block_index=index)
        if reason is not None:
            failures.append({"block_index": index, "reason": reason})
        else:
            applied += 1

    # All-or-nothing: only persist when every block applied cleanly.
    if failures:
        return {
            "path": raw_path,
            "blocks_applied": 0,
            "blocks_failed": len(failures),
            "failures": failures,
        }

    if working != original:
        try:
            target.write_text(working, encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"apply_diff: could not write {raw_path!r}: {exc}") from exc

    return {
        "path": raw_path,
        "blocks_applied": applied,
        "blocks_failed": 0,
        "failures": [],
    }
