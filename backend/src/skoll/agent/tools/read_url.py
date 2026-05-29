"""read_url tool — Jina Reader (free) primary, Trafilatura fallback.

Issue: phase-2.7.
Schema: contracts/tools/read_url.json.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    # TODO(phase-2.7)
    raise NotImplementedError
