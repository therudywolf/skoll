"""Tests for the read_url tool (Issue 2.7).

The two backends (skoll.search.jina_reader / skoll.search.trafilatura_extract) are
monkeypatched at the names imported by the tool module, so no HTTP runs here. The result
shape is asserted against contracts/tools/read_url.json's result_schema (validated in CI),
and the fetched content is verified to be untrusted-wrapped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import skoll.config as config_mod
from skoll.agent.tools import read_url
from skoll.agent.tools.registry import ToolContext
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.search.jina_reader import ReadResult

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "tools" / "read_url.json"
_URL = "https://example.com/article"


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    config_mod._settings = None
    yield
    config_mod._settings = None


def _context() -> ToolContext:
    return ToolContext(session_id="sess-1", workspace_root="workspaces/ws")


def _read_result(source: str, *, content: str = "# Body\n\nhello", truncated: bool = False) -> Any:
    return ReadResult(
        url=_URL,
        title="Example Article",
        content=content,
        source=source,
        truncated=truncated,
    )


def _stub_read(result: Any | Exception) -> Any:
    """Build an async backend ``read`` replacement returning ``result`` (or raising it)."""

    async def _read(url: str, **kwargs: Any) -> Any:
        if isinstance(result, Exception):
            raise result
        return result

    return _read


# --------------------------------------------------------------------------- #
# Jina-primary happy path + result schema + untrusted wrapping
# --------------------------------------------------------------------------- #


async def test_jina_primary_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(read_url.jina_reader, "read", _stub_read(_read_result("jina")))
    # Trafilatura must not be consulted when Jina succeeds.
    monkeypatch.setattr(
        read_url.trafilatura_extract, "read", _stub_read(RuntimeError("should not run"))
    )

    result = await read_url.handler({"url": _URL}, _context())

    assert result["url"] == _URL
    assert result["title"] == "Example Article"
    assert result["source"] == "jina"
    assert result["truncated"] is False


async def test_content_is_untrusted_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        read_url.jina_reader, "read", _stub_read(_read_result("jina", content="# Page\nbody text"))
    )

    result = await read_url.handler({"url": _URL}, _context())
    content = result["content"]
    # Wrapped with source="url" provenance carrying the fetched URL.
    assert content.startswith("<untrusted_content")
    assert content.rstrip().endswith("</untrusted_content>")
    assert 'source="url"' in content
    assert f'url="{_URL}"' in content
    assert "body text" in content


async def test_result_validates_against_contract_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import jsonschema  # type: ignore[import-untyped]

    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    monkeypatch.setattr(read_url.jina_reader, "read", _stub_read(_read_result("jina")))

    result = await read_url.handler({"url": _URL, "max_chars": 10_000}, _context())
    jsonschema.validate(instance=result, schema=contract["result_schema"])


async def test_jina_api_key_passed_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_JINA_READER_API_KEY", "jina-key-123")
    seen: dict[str, str] = {}

    async def _read(url: str, *, max_chars: int = 10_000, api_key: str = "") -> Any:
        seen["api_key"] = api_key
        return _read_result("jina")

    monkeypatch.setattr(read_url.jina_reader, "read", _read)

    await read_url.handler({"url": _URL}, _context())
    assert seen["api_key"] == "jina-key-123"


# --------------------------------------------------------------------------- #
# Fallback to Trafilatura
# --------------------------------------------------------------------------- #


async def test_falls_back_to_trafilatura_on_jina_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        read_url.jina_reader, "read", _stub_read(ToolExecutionError("Jina Reader timed out"))
    )
    monkeypatch.setattr(
        read_url.trafilatura_extract,
        "read",
        _stub_read(_read_result("trafilatura", content="# Static\nfallback body")),
    )

    result = await read_url.handler({"url": _URL}, _context())

    assert result["source"] == "trafilatura"
    assert "fallback body" in result["content"]
    assert result["content"].startswith("<untrusted_content")


async def test_both_backends_fail_raises_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(read_url.jina_reader, "read", _stub_read(ToolExecutionError("jina down")))
    monkeypatch.setattr(
        read_url.trafilatura_extract,
        "read",
        _stub_read(ToolExecutionError("trafilatura no content")),
    )

    with pytest.raises(ToolExecutionError, match="both Jina and Trafilatura failed"):
        await read_url.handler({"url": _URL}, _context())


async def test_max_chars_forwarded_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    async def _read(url: str, *, max_chars: int = 10_000, api_key: str = "") -> Any:
        seen["max_chars"] = max_chars
        return _read_result("jina")

    monkeypatch.setattr(read_url.jina_reader, "read", _read)

    await read_url.handler({"url": _URL, "max_chars": 25_000}, _context())
    assert seen["max_chars"] == 25_000


async def test_max_chars_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    async def _read(url: str, *, max_chars: int = 10_000, api_key: str = "") -> Any:
        seen["max_chars"] = max_chars
        return _read_result("jina")

    monkeypatch.setattr(read_url.jina_reader, "read", _read)

    await read_url.handler({"url": _URL, "max_chars": 999_999}, _context())
    assert seen["max_chars"] == 50_000  # clamped to contract max


# --------------------------------------------------------------------------- #
# URL validation (SSRF / scheme guard)
# --------------------------------------------------------------------------- #


async def test_missing_url_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="url"):
        await read_url.handler({}, _context())


async def test_blank_url_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="url"):
        await read_url.handler({"url": "   "}, _context())


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "data:text/html,<script>alert(1)</script>",
        "gopher://example.com",
    ],
)
async def test_non_http_scheme_rejected(bad_url: str) -> None:
    with pytest.raises(ToolValidationError, match="http"):
        await read_url.handler({"url": bad_url}, _context())


async def test_url_without_host_rejected() -> None:
    with pytest.raises(ToolValidationError, match="host"):
        await read_url.handler({"url": "http://"}, _context())


async def test_non_int_max_chars_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="max_chars"):
        await read_url.handler({"url": _URL, "max_chars": "lots"}, _context())
