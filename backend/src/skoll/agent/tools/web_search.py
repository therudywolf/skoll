"""web_search tool — SearXNG primary, DuckDuckGo fallback.

Issue: phase-2.6.
Schema: contracts/tools/web_search.json.
Backed by: skoll.search.searxng / skoll.search.duckduckgo.

This tool is **read-only** (``requires_approval: false`` / ``auto_approve_default: true``
in the descriptor): it only reads public search results, so it auto-approves.

Backend order is configurable via ``SearchSettings.primary`` (default ``searxng``):
  - primary ``searxng``: try SearXNG; on its failure *or empty results*, try DuckDuckGo.
  - primary ``duckduckgo``: try DuckDuckGo; on its failure *or empty results*, try
    SearXNG.
If both backends fail, the tool raises :class:`~skoll.errors.ToolExecutionError`.

The individual result titles/snippets come from the open web and are therefore wrapped
as untrusted content (``source="web_search"``) before they can reach the model's prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from skoll.config import get_settings
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.search import duckduckgo, searxng
from skoll.security.untrusted import wrap

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext
    from skoll.search.searxng import SearchHit

logger = structlog.get_logger(__name__)

# Mirrors contracts/tools/web_search.json -> parameters.properties.max_results.
_DEFAULT_MAX_RESULTS = 5
_MIN_MAX_RESULTS = 1
_MAX_MAX_RESULTS = 10


def _coerce_max_results(raw: object) -> int:
    """Clamp ``max_results`` into the descriptor's [1, 10] range; default when absent.

    The registry validates args against the JSON Schema before we run, so this is a
    defensive clamp that also keeps the handler correct when called directly in a test.
    """
    if raw is None:
        return _DEFAULT_MAX_RESULTS
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolValidationError("web_search: 'max_results' must be an integer")
    return max(_MIN_MAX_RESULTS, min(_MAX_MAX_RESULTS, raw))


def _coerce_site(raw: object) -> str | None:
    """Validate the optional ``site`` restriction; return a cleaned value or ``None``."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolValidationError("web_search: 'site' must be a string")
    cleaned = raw.strip()
    return cleaned or None


async def _run_searxng(query: str, max_results: int, site: str | None) -> list[SearchHit]:
    """Adapter so both backends share the ``(query, max_results, site)`` call shape."""
    base_url = get_settings().search.searxng_url
    return await searxng.search(query, base_url=base_url, max_results=max_results, site=site)


async def _run_duckduckgo(query: str, max_results: int, site: str | None) -> list[SearchHit]:
    """Run DuckDuckGo, folding any ``site:`` restriction into the query string.

    The ``duckduckgo-search`` library has no native site filter, so we prepend the
    ``site:`` operator (DuckDuckGo honours it) to mirror SearXNG behaviour.
    """
    effective_query = f"site:{site} {query}" if site else query
    return await duckduckgo.search(effective_query, max_results=max_results)


def _hit_to_result(hit: SearchHit) -> dict[str, Any]:
    """Shape one :class:`SearchHit` per result_schema.results.items.

    The title and snippet are untrusted web content and are wrapped in
    ``<untrusted_content>`` with provenance (the result URL) before reaching the prompt.
    The ``url`` itself is left bare so the agent can pass it to ``read_url``.
    """
    return {
        "title": wrap(hit.title, source="web_search", url=hit.url),
        "url": hit.url,
        "snippet": wrap(hit.snippet, source="web_search", url=hit.url),
    }


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Search the web via SearXNG (primary) with a DuckDuckGo fallback.

    args = {query: str, max_results?: int (1..10, default 5), site?: str}

    Steps:
      1. Validate ``query``; clamp ``max_results``; validate optional ``site``.
      2. Query the configured primary backend. On a :class:`ToolExecutionError` *or* an
         empty result list, fall back to the other backend.
      3. Wrap each result's title/snippet as untrusted and shape per the result_schema.

    Returns a dict matching contracts/tools/web_search.json -> result_schema:
        {"query": str, "source": "searxng"|"duckduckgo",
         "results": [{title, url, snippet}, ...]}

    Raises:
        ToolValidationError: ``query`` missing/blank, or ``max_results``/``site`` of the
            wrong type.
        ToolExecutionError: both backends failed.
    """
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolValidationError("web_search: 'query' is required and must be a non-empty string")
    query = query.strip()
    max_results = _coerce_max_results(args.get("max_results"))
    site = _coerce_site(args.get("site"))

    primary = get_settings().search.primary
    if primary == "duckduckgo":
        order: list[tuple[str, Any]] = [
            ("duckduckgo", _run_duckduckgo),
            ("searxng", _run_searxng),
        ]
    else:
        order = [
            ("searxng", _run_searxng),
            ("duckduckgo", _run_duckduckgo),
        ]

    last_error: ToolExecutionError | None = None
    for source, runner in order:
        try:
            hits = await runner(query, max_results, site)
        except ToolExecutionError as exc:
            logger.info("skoll.web_search.backend_failed", backend=source, error=str(exc))
            last_error = exc
            continue
        if not hits:
            logger.info("skoll.web_search.backend_empty", backend=source)
            continue
        return {
            "query": query,
            "source": source,
            "results": [_hit_to_result(hit) for hit in hits],
        }

    # Every backend either failed or returned nothing.
    if last_error is not None:
        raise ToolExecutionError(
            f"web_search: all backends failed (last error: {last_error})"
        ) from last_error
    # No backend errored, but none had results -> return an empty set from the primary.
    return {"query": query, "source": order[0][0], "results": []}
