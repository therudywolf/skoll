"""Unit tests for the search backends (Issues 2.6 / 2.7).

All HTTP is mocked with respx; the synchronous ``duckduckgo-search`` library is
monkeypatched. No test touches the real network.

Covers:
  - searxng.search  — parses a mocked JSON response; 5xx / timeout / bad JSON -> error.
  - duckduckgo.search — fallback via a patched DDGS().text (run through asyncio.to_thread).
  - jina_reader.read — markdown from a mocked JSON body; failure modes.
  - trafilatura_extract.read — extracts from mocked HTML; empty extract -> error.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
import respx
from skoll.errors import ToolExecutionError
from skoll.search import duckduckgo, jina_reader, searxng, trafilatura_extract

SEARXNG_URL = "http://localhost:8089"


# --------------------------------------------------------------------------- #
# SearXNG
# --------------------------------------------------------------------------- #


@respx.mock
async def test_searxng_parses_json_results() -> None:
    payload = {
        "results": [
            {"title": "Result One", "url": "https://a.example/1", "content": "snippet one"},
            {"title": "Result Two", "url": "https://b.example/2", "content": "snippet two"},
        ]
    }
    route = respx.get(f"{SEARXNG_URL}/search").mock(return_value=httpx.Response(200, json=payload))

    hits = await searxng.search("python asyncio", base_url=SEARXNG_URL, max_results=5)

    assert route.called
    # format=json and the query are sent as params.
    request = route.calls.last.request
    assert request.url.params["format"] == "json"
    assert request.url.params["q"] == "python asyncio"

    assert [h.url for h in hits] == ["https://a.example/1", "https://b.example/2"]
    assert hits[0].title == "Result One"
    assert hits[0].snippet == "snippet one"


@respx.mock
async def test_searxng_applies_site_restriction() -> None:
    route = respx.get(f"{SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    await searxng.search("decorators", base_url=SEARXNG_URL, site="docs.python.org")
    assert route.calls.last.request.url.params["q"] == "site:docs.python.org decorators"


@respx.mock
async def test_searxng_respects_max_results() -> None:
    payload = {"results": [{"url": f"https://x/{i}", "title": str(i)} for i in range(10)]}
    respx.get(f"{SEARXNG_URL}/search").mock(return_value=httpx.Response(200, json=payload))
    hits = await searxng.search("q", base_url=SEARXNG_URL, max_results=3)
    assert len(hits) == 3


@respx.mock
async def test_searxng_skips_entries_without_url() -> None:
    payload = {
        "results": [
            {"title": "no url here", "content": "ignored"},
            {"title": "ok", "url": "https://ok.example", "content": "kept"},
        ]
    }
    respx.get(f"{SEARXNG_URL}/search").mock(return_value=httpx.Response(200, json=payload))
    hits = await searxng.search("q", base_url=SEARXNG_URL)
    assert [h.url for h in hits] == ["https://ok.example"]


@respx.mock
async def test_searxng_5xx_raises_execution_error() -> None:
    respx.get(f"{SEARXNG_URL}/search").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(ToolExecutionError, match="server error"):
        await searxng.search("q", base_url=SEARXNG_URL)


@respx.mock
async def test_searxng_timeout_raises_execution_error() -> None:
    respx.get(f"{SEARXNG_URL}/search").mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(ToolExecutionError, match="timed out"):
        await searxng.search("q", base_url=SEARXNG_URL)


@respx.mock
async def test_searxng_bad_json_raises_execution_error() -> None:
    respx.get(f"{SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    with pytest.raises(ToolExecutionError, match="invalid JSON"):
        await searxng.search("q", base_url=SEARXNG_URL)


@respx.mock
async def test_searxng_missing_results_key_returns_empty() -> None:
    respx.get(f"{SEARXNG_URL}/search").mock(return_value=httpx.Response(200, json={"query": "q"}))
    hits = await searxng.search("q", base_url=SEARXNG_URL)
    assert hits == []


# --------------------------------------------------------------------------- #
# DuckDuckGo (fallback) — patch the sync library; verify it runs off-loop
# --------------------------------------------------------------------------- #


class _FakeDDGS:
    """Minimal stand-in for duckduckgo_search.DDGS used as a context manager."""

    rows: ClassVar[list[dict[str, str]]] = []
    raised: ClassVar[Exception | None] = None
    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __enter__(self) -> _FakeDDGS:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def text(self, keywords: str, **kwargs: Any) -> list[dict[str, str]]:
        type(self).last_kwargs = {"keywords": keywords, **kwargs}
        if type(self).raised is not None:
            raise type(self).raised
        return type(self).rows


async def test_duckduckgo_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeDDGS.rows = [
        {"title": "DDG One", "href": "https://d.example/1", "body": "ddg snippet one"},
        {"title": "DDG Two", "href": "https://d.example/2", "body": "ddg snippet two"},
    ]
    _FakeDDGS.raised = None
    monkeypatch.setattr(duckduckgo, "DDGS", _FakeDDGS)

    hits = await duckduckgo.search("python asyncio", max_results=5)

    assert [h.url for h in hits] == ["https://d.example/1", "https://d.example/2"]
    assert hits[0].title == "DDG One"
    assert hits[0].snippet == "ddg snippet one"
    # max_results is forwarded to the library.
    assert _FakeDDGS.last_kwargs["max_results"] == 5
    assert _FakeDDGS.last_kwargs["keywords"] == "python asyncio"


async def test_duckduckgo_skips_rows_without_href(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeDDGS.rows = [
        {"title": "no href", "body": "x"},
        {"title": "ok", "href": "https://ok.example", "body": "kept"},
    ]
    _FakeDDGS.raised = None
    monkeypatch.setattr(duckduckgo, "DDGS", _FakeDDGS)
    hits = await duckduckgo.search("q")
    assert [h.url for h in hits] == ["https://ok.example"]


async def test_duckduckgo_library_error_raises_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeDDGS.rows = []
    _FakeDDGS.raised = RuntimeError("Ratelimit")
    monkeypatch.setattr(duckduckgo, "DDGS", _FakeDDGS)
    with pytest.raises(ToolExecutionError, match="DuckDuckGo search failed"):
        await duckduckgo.search("q")


# --------------------------------------------------------------------------- #
# Jina Reader
# --------------------------------------------------------------------------- #

JINA_TARGET = "https://example.com/article"


@respx.mock
async def test_jina_returns_markdown_from_json() -> None:
    body = {
        "code": 200,
        "data": {
            "title": "Example Article",
            "content": "# Example Article\n\nSome **markdown** body.",
            "url": JINA_TARGET,
        },
    }
    route = respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(
        return_value=httpx.Response(200, json=body)
    )

    result = await jina_reader.read(JINA_TARGET, max_chars=10_000)

    assert route.called
    assert result.source == "jina"
    assert result.title == "Example Article"
    assert "**markdown**" in result.content
    assert result.truncated is False
    # We request JSON.
    assert route.calls.last.request.headers["accept"] == "application/json"


@respx.mock
async def test_jina_sends_api_key_as_bearer() -> None:
    body = {"data": {"title": "t", "content": "body content"}}
    route = respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(
        return_value=httpx.Response(200, json=body)
    )
    await jina_reader.read(JINA_TARGET, api_key="jina-secret-key")
    assert route.calls.last.request.headers["authorization"] == "Bearer jina-secret-key"


@respx.mock
async def test_jina_truncates_to_max_chars() -> None:
    body = {"data": {"title": "t", "content": "x" * 5000}}
    respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(return_value=httpx.Response(200, json=body))
    result = await jina_reader.read(JINA_TARGET, max_chars=1000)
    assert len(result.content) == 1000
    assert result.truncated is True


@respx.mock
async def test_jina_falls_back_to_raw_text_when_not_json() -> None:
    respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(
        return_value=httpx.Response(200, text="# Raw markdown body")
    )
    result = await jina_reader.read(JINA_TARGET)
    assert result.content == "# Raw markdown body"
    assert result.title == ""


@respx.mock
async def test_jina_5xx_raises_execution_error() -> None:
    respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(return_value=httpx.Response(503))
    with pytest.raises(ToolExecutionError, match="server error"):
        await jina_reader.read(JINA_TARGET)


@respx.mock
async def test_jina_empty_content_raises_execution_error() -> None:
    respx.get(f"https://r.jina.ai/{JINA_TARGET}").mock(return_value=httpx.Response(200, text="   "))
    with pytest.raises(ToolExecutionError, match="empty content"):
        await jina_reader.read(JINA_TARGET)


# --------------------------------------------------------------------------- #
# Trafilatura (fallback)
# --------------------------------------------------------------------------- #

TRAF_TARGET = "https://static.example/post"

_HTML = """
<html><head><title>Head Title</title></head>
<body><article>
<h1>Post Header</h1>
<p>This is the first paragraph of the article with enough text to be extracted.</p>
<p>Here is a second paragraph that adds more substantive body content for parsing.</p>
</article></body></html>
"""


@respx.mock
async def test_trafilatura_extracts_from_html() -> None:
    route = respx.get(TRAF_TARGET).mock(return_value=httpx.Response(200, text=_HTML))

    result = await trafilatura_extract.read(TRAF_TARGET, max_chars=10_000)

    assert route.called
    assert result.source == "trafilatura"
    assert "first paragraph" in result.content
    assert result.title  # a non-empty title was extracted
    assert result.truncated is False


@respx.mock
async def test_trafilatura_truncates() -> None:
    long_para = "<p>" + ("word " * 2000) + "</p>"
    html = f"<html><body><article><h1>T</h1>{long_para}</article></body></html>"
    respx.get(TRAF_TARGET).mock(return_value=httpx.Response(200, text=html))
    result = await trafilatura_extract.read(TRAF_TARGET, max_chars=1000)
    assert len(result.content) == 1000
    assert result.truncated is True


@respx.mock
async def test_trafilatura_no_content_raises_execution_error() -> None:
    # An empty document yields no extractable main content.
    respx.get(TRAF_TARGET).mock(return_value=httpx.Response(200, text="<html></html>"))
    with pytest.raises(ToolExecutionError, match="could not extract"):
        await trafilatura_extract.read(TRAF_TARGET)


@respx.mock
async def test_trafilatura_4xx_raises_execution_error() -> None:
    respx.get(TRAF_TARGET).mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(ToolExecutionError, match="rejected"):
        await trafilatura_extract.read(TRAF_TARGET)
