"""read_url tool — Jina Reader (free) primary, Trafilatura fallback.

Issue: phase-2.7.
Schema: contracts/tools/read_url.json.
Backed by: skoll.search.jina_reader / skoll.search.trafilatura_extract.

This tool is **read-only** (``requires_approval: false`` / ``auto_approve_default: true``
in the descriptor): it only fetches a public URL, so it auto-approves.

Backend order is fixed (the contract names Jina as primary): try Jina Reader, and on its
failure fall back to Trafilatura. The fetched page is **untrusted external content** and
may contain prompt-injection attempts, so the markdown is wrapped with
``security.untrusted.wrap(source="url", url=...)`` before it can reach the model's
prompt. If both backends fail, the tool raises
:class:`~skoll.errors.ToolExecutionError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from skoll.config import get_settings
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.search import jina_reader, trafilatura_extract
from skoll.security.untrusted import wrap

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolContext

logger = structlog.get_logger(__name__)

# Mirrors contracts/tools/read_url.json -> parameters.properties.max_chars.
_DEFAULT_MAX_CHARS = 10_000
_MIN_MAX_CHARS = 1_000
_MAX_MAX_CHARS = 50_000

# URL schemes we will fetch. Anything else (file:, data:, ftp:, gopher:, ...) is rejected
# to avoid SSRF-style local reads or unexpected protocol handling.
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _coerce_max_chars(raw: object) -> int:
    """Clamp ``max_chars`` into the descriptor's [1000, 50000] range; default when absent.

    Defensive clamp mirroring the JSON Schema, so the handler stays correct when called
    directly in a test (without the registry's prior validation).
    """
    if raw is None:
        return _DEFAULT_MAX_CHARS
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolValidationError("read_url: 'max_chars' must be an integer")
    return max(_MIN_MAX_CHARS, min(_MAX_MAX_CHARS, raw))


def _validate_url(raw: object) -> str:
    """Validate ``url`` is a non-empty absolute http(s) URL; return the cleaned value.

    Rejects non-http(s) schemes so the tool cannot be coerced into reading ``file://``
    paths or other local/SSRF targets via either backend's fetch.
    """
    from urllib.parse import urlparse

    if not isinstance(raw, str) or not raw.strip():
        raise ToolValidationError("read_url: 'url' is required and must be a non-empty string")
    cleaned = raw.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ToolValidationError(
            f"read_url: 'url' must be an absolute http(s) URL (got scheme {parsed.scheme!r})"
        )
    if not parsed.netloc:
        raise ToolValidationError("read_url: 'url' is missing a host")
    return cleaned


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Fetch a URL and return its content as untrusted-wrapped markdown.

    args = {url: str (absolute http/https), max_chars?: int (1000..50000, default 10000)}

    Steps:
      1. Validate ``url`` (http/https only) and clamp ``max_chars``.
      2. Fetch via Jina Reader (primary). On a :class:`ToolExecutionError`, fall back to
         Trafilatura.
      3. Wrap the markdown in ``<untrusted_content source="url" url="...">`` — fetched web
         content is untrusted and may carry prompt-injection — and shape per result_schema.

    Returns a dict matching contracts/tools/read_url.json -> result_schema:
        {"url": str, "title": str, "content": <untrusted-wrapped markdown>,
         "source": "jina"|"trafilatura", "truncated": bool}

    Raises:
        ToolValidationError: ``url`` missing/blank/non-http(s), or ``max_chars`` not an int.
        ToolExecutionError: both Jina and Trafilatura failed.
    """
    url = _validate_url(args.get("url"))
    max_chars = _coerce_max_chars(args.get("max_chars"))

    api_key = get_settings().search.jina_reader_api_key

    try:
        result = await jina_reader.read(url, max_chars=max_chars, api_key=api_key)
    except ToolExecutionError as jina_exc:
        logger.info("skoll.read_url.jina_failed", url=url, error=str(jina_exc))
        try:
            result = await trafilatura_extract.read(url, max_chars=max_chars)
        except ToolExecutionError as traf_exc:
            logger.info("skoll.read_url.trafilatura_failed", url=url, error=str(traf_exc))
            raise ToolExecutionError(
                f"read_url: both Jina and Trafilatura failed for {url} "
                f"(jina: {jina_exc}; trafilatura: {traf_exc})"
            ) from traf_exc

    wrapped = wrap(result.content, source="url", url=result.url)
    return {
        "url": result.url,
        "title": result.title,
        "content": wrapped,
        "source": result.source,
        "truncated": result.truncated,
    }
