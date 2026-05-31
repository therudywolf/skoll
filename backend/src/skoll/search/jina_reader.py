"""Jina Reader — URL -> markdown.

Issue: phase-2.7.

Fetches ``https://r.jina.ai/<url>`` which renders the target page (including JS-heavy
SPAs) and returns clean markdown. Free tier is 50K/mo without an API key; an optional
key (``SearchSettings.jina_reader_api_key``) raises the limit and is sent as a bearer
token.

We request ``Accept: application/json`` so the response carries a structured
``{data: {title, content, url}}`` body — that gives us a reliable page title. If a
deployment ever returns plain markdown instead, we degrade to using the raw text as the
content with an empty title.

This is the *primary* ``read_url`` backend; on failure the tool falls back to
:mod:`skoll.search.trafilatura_extract`, so failures raise
:class:`~skoll.errors.ToolExecutionError` rather than being swallowed.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from skoll.errors import ToolExecutionError

logger = structlog.get_logger(__name__)

_JINA_BASE = "https://r.jina.ai/"

# Jina renders JS and can be slow on heavy pages; allow a generous-but-bounded budget.
# read_url falls back to Trafilatura on timeout, so this must not hang the loop forever.
_TIMEOUT_SECONDS = 30.0

_HTTP_SERVER_ERROR = 500
_HTTP_CLIENT_ERROR = 400


@dataclass(frozen=True)
class ReadResult:
    url: str
    title: str
    content: str  # markdown
    source: str  # 'jina'
    truncated: bool


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Clamp ``text`` to ``max_chars``; return the (possibly clipped) text and a flag."""
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _parse_payload(payload: object) -> tuple[str, str]:
    """Extract ``(title, content)`` from a Jina JSON body.

    Jina's JSON envelope is ``{"code": 200, "data": {"title", "content", "url", ...}}``.
    Falls back to empty strings for absent fields so the caller always gets ``str``.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return "", ""
    title = data.get("title")
    content = data.get("content")
    return (
        str(title) if isinstance(title, str) else "",
        str(content) if isinstance(content, str) else "",
    )


async def read(url: str, *, max_chars: int = 10_000, api_key: str = "") -> ReadResult:
    """Fetch ``url`` via Jina Reader and return its content as markdown.

    Args:
        url: Absolute URL to fetch.
        max_chars: Truncate the returned markdown to this length (1000..50000 per
            contract).
        api_key: Optional Jina key; sent as ``Authorization: Bearer <key>`` when present.

    Returns:
        A :class:`ReadResult` with ``source="jina"``.

    Raises:
        ToolExecutionError: on timeout, connection failure, a 4xx/5xx status, an
            unparseable body, or empty extracted content. The caller falls back to
            Trafilatura.
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    endpoint = f"{_JINA_BASE}{url}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT_SECONDS),
            follow_redirects=True,
        ) as client:
            response = await client.get(endpoint, headers=headers)
    except httpx.TimeoutException as exc:
        raise ToolExecutionError(f"Jina Reader timed out: {exc!s}") from exc
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"Jina Reader request failed: {exc!s}") from exc

    if response.status_code >= _HTTP_SERVER_ERROR:
        raise ToolExecutionError(f"Jina Reader server error (HTTP {response.status_code})")
    if response.status_code >= _HTTP_CLIENT_ERROR:
        raise ToolExecutionError(f"Jina Reader rejected the URL (HTTP {response.status_code})")

    title = ""
    content = ""
    try:
        payload = response.json()
    except ValueError:
        # Some deployments return raw markdown instead of JSON; use it directly.
        payload = None
    if payload is not None:
        title, content = _parse_payload(payload)
    if not content:
        # Either non-JSON, or JSON with no usable content -> fall back to the raw body.
        content = response.text

    content = content.strip()
    if not content:
        raise ToolExecutionError("Jina Reader returned empty content")

    clipped, truncated = _truncate(content, max_chars)
    return ReadResult(
        url=url,
        title=title.strip(),
        content=clipped,
        source="jina",
        truncated=truncated,
    )
