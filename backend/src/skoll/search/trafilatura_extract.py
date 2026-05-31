"""Trafilatura fallback for read_url when Jina is unavailable.

Issue: phase-2.7.

Trafilatura works well on static HTML but not on heavy SPAs (Jina handles those). It is
the *fallback* path for the ``read_url`` tool.

We fetch the page ourselves with ``httpx.AsyncClient`` (NOT ``trafilatura.fetch_url``,
which is synchronous and would block the event loop), then run the CPU-bound
``trafilatura.extract`` / ``extract_metadata`` parsing inside :func:`asyncio.to_thread`.
Content is rendered as markdown to match the tool contract.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
import trafilatura
from trafilatura.metadata import extract_metadata

from skoll.errors import ToolExecutionError
from skoll.search.jina_reader import ReadResult

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 20.0

_HTTP_SERVER_ERROR = 500
_HTTP_CLIENT_ERROR = 400

# A browser-ish UA: some sites 403 the default httpx agent. No tracking value sent.
_USER_AGENT = "Mozilla/5.0 (compatible; SkollBot/0.1; +https://github.com/therudywolf/skoll)"


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Clamp ``text`` to ``max_chars``; return the (possibly clipped) text and a flag."""
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _extract_sync(html: str, url: str) -> tuple[str, str]:
    """Run Trafilatura's parsing — call only inside ``asyncio.to_thread``.

    Returns ``(title, markdown_content)``. ``trafilatura.extract`` returns ``None`` when
    it finds no main content; that is surfaced to the caller as an empty content string.
    """
    content = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
    )
    title = ""
    try:
        meta = extract_metadata(html)
    except Exception:  # metadata parsing is best-effort; never fail the read for a title
        meta = None
    if meta is not None:
        meta_title = getattr(meta, "title", None)
        if isinstance(meta_title, str):
            title = meta_title
    return title, content or ""


async def read(url: str, *, max_chars: int = 10_000) -> ReadResult:
    """Fetch ``url`` with httpx and extract its main content as markdown via Trafilatura.

    Args:
        url: Absolute URL to fetch.
        max_chars: Truncate the returned markdown to this length (1000..50000 per
            contract).

    Returns:
        A :class:`ReadResult` with ``source="trafilatura"``.

    Raises:
        ToolExecutionError: on timeout, connection failure, a 4xx/5xx status, or when
            Trafilatura extracts no usable content. As the fallback path, this is terminal
            for the request.
    """
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_SECONDS),
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ToolExecutionError(f"Trafilatura fetch timed out: {exc!s}") from exc
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"Trafilatura fetch failed: {exc!s}") from exc

    if response.status_code >= _HTTP_SERVER_ERROR:
        raise ToolExecutionError(f"Trafilatura fetch server error (HTTP {response.status_code})")
    if response.status_code >= _HTTP_CLIENT_ERROR:
        raise ToolExecutionError(f"Trafilatura fetch rejected (HTTP {response.status_code})")

    title, content = await asyncio.to_thread(_extract_sync, response.text, url)

    content = content.strip()
    if not content:
        raise ToolExecutionError("Trafilatura could not extract content from the page")

    clipped, truncated = _truncate(content, max_chars)
    return ReadResult(
        url=url,
        title=title.strip(),
        content=clipped,
        source="trafilatura",
        truncated=truncated,
    )
