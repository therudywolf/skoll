"""DuckDuckGo fallback search.

Issue: phase-2.6.

Uses the ``duckduckgo-search`` library (``DDGS().text``). That library is *synchronous*
and uses ``requests`` under the hood, so the blocking call is dispatched to a worker
thread via :func:`asyncio.to_thread` to keep the agent loop's event loop free (per
AGENTS.md §6: no synchronous HTTP on the loop).

Rate limiting (``RatelimitException``) and other library errors are normalised to
:class:`~skoll.errors.ToolExecutionError`. The ``web_search`` tool uses this only as a
*fallback* when SearXNG is unavailable, so an error here is terminal for the request.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from duckduckgo_search import DDGS

from skoll.errors import ToolExecutionError
from skoll.search.searxng import SearchHit

logger = structlog.get_logger(__name__)


def _coerce_hit(raw: object) -> SearchHit | None:
    """Map one ``DDGS().text`` row to a :class:`SearchHit`.

    The library yields dicts shaped ``{"title", "href", "body"}``. Rows without an
    ``href`` are skipped; a missing title falls back to the URL.
    """
    if not isinstance(raw, dict):
        return None
    url = raw.get("href")
    if not isinstance(url, str) or not url:
        return None
    title = raw.get("title")
    body = raw.get("body")
    return SearchHit(
        title=str(title) if isinstance(title, str) and title else url,
        url=url,
        snippet=str(body) if isinstance(body, str) else "",
    )


def _search_sync(query: str, max_results: int) -> list[dict[str, Any]]:
    """Blocking DuckDuckGo text search — must only be called inside ``asyncio.to_thread``.

    Wrapped so the network/library call never runs on the event loop. Returns the raw
    list of result dicts from the library.
    """
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def search(query: str, *, max_results: int = 5) -> list[SearchHit]:
    """Run a DuckDuckGo text search off-loop and return up to ``max_results`` hits.

    Args:
        query: User search string.
        max_results: Cap on returned hits (1..10 per the tool contract).

    Returns:
        A possibly-empty list of :class:`SearchHit`.

    Raises:
        ToolExecutionError: if the library raises (rate limit, network error, etc.). As
            this is the fallback path, the caller cannot recover further.
    """
    cleaned = query.strip()
    try:
        raw_results = await asyncio.to_thread(_search_sync, cleaned, max_results)
    except Exception as exc:  # duckduckgo-search raises its own exception hierarchy
        raise ToolExecutionError(f"DuckDuckGo search failed: {exc!s}") from exc

    hits: list[SearchHit] = []
    for raw in raw_results:
        hit = _coerce_hit(raw)
        if hit is not None:
            hits.append(hit)
        if len(hits) >= max_results:
            break
    return hits
