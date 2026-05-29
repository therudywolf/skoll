"""Tests for POST /api/chat (Issue 0.4).

LM Studio is mocked via respx. Validates success shape, error shape, strict body
validation (extra fields), and the 1 MB body limit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import skoll.config as config_mod
from skoll.app import create_app

LM_BASE = "http://127.0.0.1:1234"


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    config_mod._settings = None
    yield
    config_mod._settings = None


def _fixture(name: str) -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "lm_studio" / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def _post_chat(body: Any, *, raw: bytes | None = None) -> httpx.Response:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if raw is not None:
            return await client.post(
                "/api/chat",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
        return await client.post("/api/chat", json=body)


@respx.mock
async def test_chat_happy_path() -> None:
    respx.post(f"{LM_BASE}/api/v1/chat").mock(
        return_value=httpx.Response(200, json=_fixture("chat_simple_nontool.json"))
    )
    resp = await _post_chat(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "qwen2.5-coder-32b-instruct",
        }
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"content", "model"}
    assert body["model"] == "qwen2.5-coder-32b-instruct"
    assert body["content"].startswith("Hello!")


@respx.mock
async def test_chat_resolves_model_from_list_when_omitted() -> None:
    respx.get(f"{LM_BASE}/api/v1/models").mock(
        return_value=httpx.Response(200, json=_fixture("models_list.json"))
    )
    respx.post(f"{LM_BASE}/api/v1/chat").mock(
        return_value=httpx.Response(200, json=_fixture("chat_simple_nontool.json"))
    )
    resp = await _post_chat({"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    # Falls back to the first listed model.
    assert resp.json()["model"] == "qwen2.5-coder-32b-instruct"


@respx.mock
async def test_chat_bad_model_returns_400_error_shape() -> None:
    respx.post(f"{LM_BASE}/api/v1/chat").mock(
        return_value=httpx.Response(400, json=_fixture("error_400_invalid_model.json"))
    )
    resp = await _post_chat(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "does-not-exist",
        }
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message"}
    assert body["error"]["code"] == "lmstudio.error"


async def test_chat_rejects_extra_fields() -> None:
    resp = await _post_chat(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "m",
            "totally_unexpected": "field",
        }
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "request.invalid"


async def test_chat_rejects_extra_field_in_message() -> None:
    resp = await _post_chat(
        {
            "messages": [{"role": "user", "content": "hi", "name": "x"}],
            "model": "m",
        }
    )
    assert resp.status_code == 422


async def test_chat_rejects_empty_messages() -> None:
    resp = await _post_chat({"messages": [], "model": "m"})
    assert resp.status_code == 422


async def test_chat_body_over_1mb_rejected() -> None:
    # Build a >1 MB JSON body.
    huge = "x" * (1024 * 1024 + 10)
    raw = json.dumps({"messages": [{"role": "user", "content": huge}], "model": "m"}).encode(
        "utf-8"
    )
    assert len(raw) > 1024 * 1024
    resp = await _post_chat(None, raw=raw)
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "lmstudio.error"
    # The message must NOT echo the submitted content.
    assert "x" * 100 not in body["error"]["message"]


@respx.mock
async def test_chat_error_message_does_not_echo_user_content() -> None:
    # LM Studio returns a 400 → endpoint replies 400, and the user's content must not
    # appear anywhere in the error envelope (leak vector, Issue 0.4).
    respx.post(f"{LM_BASE}/api/v1/chat").mock(
        return_value=httpx.Response(400, json=_fixture("error_400_invalid_model.json"))
    )
    prompt_marker = "PRIVATE_USER_PROMPT_MARKER_8675309"
    resp = await _post_chat(
        {
            "messages": [{"role": "user", "content": prompt_marker}],
            "model": "m",
        }
    )
    assert resp.status_code == 400
    assert prompt_marker not in resp.text
