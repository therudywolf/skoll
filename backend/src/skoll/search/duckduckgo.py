"""DuckDuckGo fallback search.

Issue: phase-2.6.

Uses the `duckduckgo-search` library. Handles RatelimitException by raising a
SkollError so the caller can fall back to SearXNG (or vice versa).
"""

from __future__ import annotations

from skoll.search.searxng import SearchHit


async def search(query: str, *, max_results: int = 5) -> list[SearchHit]:
    # TODO(phase-2.6)
    raise NotImplementedError
