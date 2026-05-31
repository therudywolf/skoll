"""SearXNG JSON API client.

Issue: phase-2.6.

Endpoint: ``GET {SEARXNG_URL}/search?q=<query>&format=json``.

This is the *primary* web-search backend (free, self-hosted, no API key). The
``web_search`` tool falls back to :mod:`skoll.search.duckduckgo` when this backend
returns a 5xx, times out, or yields no results — so failures here are surfaced as
:class:`~skoll.errors.ToolExecutionError` (or an empty list) rather than swallowed.

All I/O is async via ``httpx.AsyncClient``; no synchronous HTTP libraries are used.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from skoll.errors import ToolExecutionError

logger = structlog.get_logger(__name__)

# Total request budget for a SearXNG query. Kept short: SearXNG is local, and the
# tool falls back to DuckDuckGo on timeout, so we must not block the agent loop.
_TIMEOUT_SECONDS = 10.0

# HTTP status-class boundaries (named to avoid bare magic numbers in branches).
_HTTP_SERVER_ERROR = 500
_HTTP_CLIENT_ERROR = 400


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


def _build_query(query: str, site: str | None) -> str:
    """Compose the SearXNG ``q`` value, applying an optional ``site:`` restriction.

    The ``site`` value is stripped and (when present) prefixed verbatim; httpx handles
    URL-encoding of the whole parameter, so no manual escaping is needed here.
    """
    cleaned = query.strip()
    if site:
        site_clean = site.strip()
        if site_clean:
            return f"site:{site_clean} {cleaned}"
    return cleaned


def _coerce_hit(raw: object) -> SearchHit | None:
    """Map one SearXNG result object to a :class:`SearchHit`.

    Returns ``None`` for entries without a usable URL (e.g. ``infobox`` / ``suggestion``
    rows). SearXNG names the snippet field ``content``; ``title`` may be absent for some
    engines, in which case the URL is used as a human-readable fallback.
    """
    if not isinstance(raw, dict):
        return None
    url = raw.get("url")
    if not isinstance(url, str) or not url:
        return None
    title = raw.get("title")
    snippet = raw.get("content")
    return SearchHit(
        title=str(title) if isinstance(title, str) and title else url,
        url=url,
        snippet=str(snippet) if isinstance(snippet, str) else "",
    )


def _parse_results(payload: object, max_results: int) -> list[SearchHit]:
    """Extract up to ``max_results`` hits from a parsed SearXNG JSON body."""
    if not isinstance(payload, dict):
        raise ToolExecutionError("SearXNG returned a non-object JSON response")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    hits: list[SearchHit] = []
    for raw in raw_results:
        hit = _coerce_hit(raw)
        if hit is not None:
            hits.append(hit)
        if len(hits) >= max_results:
            break
    return hits


async def search(
    query: str,
    *,
    base_url: str,
    max_results: int = 5,
    site: str | None = None,
) -> list[SearchHit]:
    """Query the SearXNG JSON API and return up to ``max_results`` hits.

    Args:
        query: User search string.
        base_url: SearXNG base URL (e.g. ``http://localhost:8089``); from
            ``SearchSettings.searxng_url``.
        max_results: Cap on returned hits (1..10 per the tool contract).
        site: Optional ``site:`` restriction (e.g. ``github.com``).

    Returns:
        A possibly-empty list of :class:`SearchHit`. Empty is a valid result and signals
        the caller to fall back to DuckDuckGo.

    Raises:
        ToolExecutionError: on timeout, connection failure, a 5xx/4xx HTTP status, or an
            unparseable / non-object JSON body. The caller treats this as "primary failed,
            fall back".
    """
    params = {
        "q": _build_query(query, site),
        "format": "json",
    }
    endpoint = f"{base_url.rstrip('/')}/search"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT_SECONDS)) as client:
            response = await client.get(endpoint, params=params)
    except httpx.TimeoutException as exc:
        raise ToolExecutionError(f"SearXNG request timed out: {exc!s}") from exc
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"SearXNG request failed: {exc!s}") from exc

    if response.status_code >= _HTTP_SERVER_ERROR:
        raise ToolExecutionError(f"SearXNG server error (HTTP {response.status_code})")
    if response.status_code >= _HTTP_CLIENT_ERROR:
        raise ToolExecutionError(f"SearXNG request rejected (HTTP {response.status_code})")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolExecutionError(f"SearXNG returned invalid JSON: {exc!s}") from exc

    return _parse_results(payload, max_results)
