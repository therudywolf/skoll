"""SearXNG JSON API client.

Issue: phase-2.6.

Endpoint: {SEARXNG_URL}/search?q=<query>&format=json
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


async def search(query: str, *, max_results: int = 5, site: str | None = None) -> list[SearchHit]:
    # TODO(phase-2.6)
    raise NotImplementedError
