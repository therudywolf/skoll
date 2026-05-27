"""web_search tool — SearXNG primary, DuckDuckGo fallback.

Issue: phase-2.6.
Schema: contracts/tools/web_search.json.
Backed by: skoll.search.searxng / skoll.search.duckduckgo
"""

from __future__ import annotations

from typing import Any


async def handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    # TODO(phase-2.6)
    raise NotImplementedError
