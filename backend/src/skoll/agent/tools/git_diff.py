"""git_diff tool — read-only.

Issue: phase-3.4.
Schema: contracts/tools/git_diff.json.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    # TODO(phase-3.4): use pygit2 or dulwich; run inside sandbox for safety
    raise NotImplementedError
