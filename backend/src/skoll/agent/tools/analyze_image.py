"""analyze_image tool — vision pipeline from PhotoAISorter.

Issue: phase-3.6.
Schema: contracts/tools/analyze_image.json.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    # TODO(phase-3.6)
    raise NotImplementedError
