"""Tests for the web_search tool (Issue 2.6).

The two backends (skoll.search.searxng / skoll.search.duckduckgo) are monkeypatched at
the names imported by the tool module, so no HTTP runs here. The result shape is asserted
against contracts/tools/web_search.json's result_schema (validated in CI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import skoll.config as config_mod
from skoll.agent.tools import web_search
from skoll.agent.tools.registry import ToolContext
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.search.searxng import SearchHit

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "tools" / "web_search.json"


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    """Each test sees a freshly-built Settings (the singleton is cached)."""
    config_mod._settings = None
    yield
    config_mod._settings = None


def _context() -> ToolContext:
    return ToolContext(session_id="sess-1", workspace_root="workspaces/ws")


def _hits(*urls: str) -> list[SearchHit]:
    return [SearchHit(title=f"Title {u}", url=u, snippet=f"snippet {u}") for u in urls]


def _stub_backend(result: list[SearchHit] | Exception) -> Any:
    """Build an async backend replacement returning ``result`` (or raising it)."""

    async def _run(query: str, *args: Any, **kwargs: Any) -> list[SearchHit]:
        if isinstance(result, Exception):
            raise result
        return result

    return _run


# --------------------------------------------------------------------------- #
# SearXNG-primary happy path + result schema
# --------------------------------------------------------------------------- #


async def test_searxng_primary_returns_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_search.searxng, "search", _stub_backend(_hits("https://a/1")))
    # DDG must not be consulted when SearXNG succeeds.
    monkeypatch.setattr(
        web_search.duckduckgo, "search", _stub_backend(RuntimeError("should not be called"))
    )

    result = await web_search.handler({"query": "python asyncio"}, _context())

    assert result["query"] == "python asyncio"
    assert result["source"] == "searxng"
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://a/1"


async def test_result_validates_against_contract_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import jsonschema  # type: ignore[import-untyped]

    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        web_search.searxng, "search", _stub_backend(_hits("https://a/1", "https://b/2"))
    )

    result = await web_search.handler({"query": "q", "max_results": 5}, _context())
    jsonschema.validate(instance=result, schema=contract["result_schema"])


async def test_titles_and_snippets_are_untrusted_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_search.searxng, "search", _stub_backend(_hits("https://a/1")))

    result = await web_search.handler({"query": "q"}, _context())
    item = result["results"][0]
    # Title + snippet wrapped with web_search provenance; the URL stays bare.
    assert item["title"].startswith("<untrusted_content")
    assert 'source="web_search"' in item["title"]
    assert 'url="https://a/1"' in item["title"]
    assert item["snippet"].startswith("<untrusted_content")
    assert item["url"] == "https://a/1"


# --------------------------------------------------------------------------- #
# Fallback to DuckDuckGo
# --------------------------------------------------------------------------- #


async def test_falls_back_to_ddg_on_searxng_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_search.searxng, "search", _stub_backend(ToolExecutionError("SearXNG server error"))
    )
    monkeypatch.setattr(web_search.duckduckgo, "search", _stub_backend(_hits("https://ddg/1")))

    result = await web_search.handler({"query": "q"}, _context())

    assert result["source"] == "duckduckgo"
    assert result["results"][0]["url"] == "https://ddg/1"


async def test_falls_back_to_ddg_on_searxng_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_search.searxng,
        "search",
        _stub_backend(ToolExecutionError("SearXNG request timed out")),
    )
    monkeypatch.setattr(web_search.duckduckgo, "search", _stub_backend(_hits("https://ddg/2")))

    result = await web_search.handler({"query": "q"}, _context())
    assert result["source"] == "duckduckgo"


async def test_falls_back_to_ddg_on_searxng_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_search.searxng, "search", _stub_backend([]))
    monkeypatch.setattr(web_search.duckduckgo, "search", _stub_backend(_hits("https://ddg/3")))

    result = await web_search.handler({"query": "q"}, _context())
    assert result["source"] == "duckduckgo"
    assert result["results"][0]["url"] == "https://ddg/3"


async def test_both_backends_fail_raises_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_search.searxng, "search", _stub_backend(ToolExecutionError("searxng down"))
    )
    monkeypatch.setattr(
        web_search.duckduckgo, "search", _stub_backend(ToolExecutionError("ddg ratelimit"))
    )

    with pytest.raises(ToolExecutionError, match="all backends failed"):
        await web_search.handler({"query": "q"}, _context())


async def test_both_backends_empty_returns_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_search.searxng, "search", _stub_backend([]))
    monkeypatch.setattr(web_search.duckduckgo, "search", _stub_backend([]))

    result = await web_search.handler({"query": "q"}, _context())
    assert result["source"] == "searxng"
    assert result["results"] == []


# --------------------------------------------------------------------------- #
# primary=duckduckgo flips the order
# --------------------------------------------------------------------------- #


async def test_primary_duckduckgo_tries_ddg_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_PRIMARY", "duckduckgo")
    monkeypatch.setattr(web_search.duckduckgo, "search", _stub_backend(_hits("https://ddg/first")))
    monkeypatch.setattr(
        web_search.searxng, "search", _stub_backend(RuntimeError("should not be called"))
    )

    result = await web_search.handler({"query": "q"}, _context())
    assert result["source"] == "duckduckgo"
    assert result["results"][0]["url"] == "https://ddg/first"


async def test_primary_duckduckgo_falls_back_to_searxng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SKOLL_PRIMARY", "duckduckgo")
    monkeypatch.setattr(
        web_search.duckduckgo, "search", _stub_backend(ToolExecutionError("ddg down"))
    )
    monkeypatch.setattr(web_search.searxng, "search", _stub_backend(_hits("https://sx/1")))

    result = await web_search.handler({"query": "q"}, _context())
    assert result["source"] == "searxng"


# --------------------------------------------------------------------------- #
# argument validation
# --------------------------------------------------------------------------- #


async def test_missing_query_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="query"):
        await web_search.handler({}, _context())


async def test_blank_query_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="query"):
        await web_search.handler({"query": "   "}, _context())


async def test_max_results_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    async def _run(query: str, max_results: int, site: str | None) -> list[SearchHit]:
        seen["max_results"] = max_results
        return _hits("https://a/1")

    monkeypatch.setattr(web_search.searxng, "search", _stub_backend(_hits("https://a/1")))
    monkeypatch.setattr(web_search, "_run_searxng", _run)

    await web_search.handler({"query": "q", "max_results": 99}, _context())
    assert seen["max_results"] == 10  # clamped to contract max


async def test_non_int_max_results_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="max_results"):
        await web_search.handler({"query": "q", "max_results": "five"}, _context())


async def test_site_restriction_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str | None] = {}

    async def _run(query: str, max_results: int, site: str | None) -> list[SearchHit]:
        seen["site"] = site
        return _hits("https://a/1")

    monkeypatch.setattr(web_search, "_run_searxng", _run)

    await web_search.handler({"query": "q", "site": "github.com"}, _context())
    assert seen["site"] == "github.com"
