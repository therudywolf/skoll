"""read_file tool.

Issue: phase-2.1.
Schema: contracts/tools/read_file.json.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """
    Steps:
      1. skoll.security.path.safe_resolve(args['path'], context.workspace_root)
      2. Read file (UTF-8, with size cap from settings)
      3. Slice lines if start_line/end_line given
      4. skoll.security.secrets.scrub() over content
      5. skoll.security.untrusted.wrap() with source=file, path, lines, redaction count
      6. Return per result_schema
    """
    # TODO(phase-2.1)
    raise NotImplementedError
