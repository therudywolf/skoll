"""Unit tests for the async LM Studio client (Issue 0.3).

LM Studio is mocked via respx — these never touch a real server.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import skoll.config as config_mod
from skoll.errors import LMStudioAuthError, LMStudioError
from skoll.lm.client import (
    LMStudioClient,
    extract_assistant_content,
)
from skoll.lm.reasoning import is_reasoning, strip_think_block

BASE_URL = "http://127.0.0.1:1234"


def _load_fixture(name: str) -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "lm_studio" / name
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    """Ensure each test sees a freshly-built Settings (the singleton is cached)."""
    config_mod._settings = None
    yield
    config_mod._settings = None


# --------------------------------------------------------------------------- #
# reasoning helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("qwen3-coder-32b", True),
        ("qwen3-coder-30b-a3b-instruct", True),
        ("deepseek-r1-distill-qwen-7b", True),
        ("nvidia-nemotron-49b", True),
        ("o3-mini", True),
        ("qwen2.5-coder-32b", False),
        ("qwen2.5-coder-32b-instruct", False),
        ("llama-3.1-8b-instruct", False),
        ("gemma-2-9b-it", False),
    ],
)
def test_is_reasoning(model: str, expected: bool) -> None:
    assert is_reasoning(model) is expected


def test_strip_think_block() -> None:
    text = "<think>secret chain of thought\nmore lines</think>Here is the answer."
    assert strip_think_block(text) == "Here is the answer."


def test_strip_think_block_no_block() -> None:
    assert strip_think_block("just text") == "just text"


# --------------------------------------------------------------------------- #
# from_settings
# --------------------------------------------------------------------------- #


def test_from_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_LMSTUDIO_BASE_URL", "http://127.0.0.1:4321")
    monkeypatch.setenv("SKOLL_LMSTUDIO_API_KEY", "sk-lm-test:secret")
    monkeypatch.setenv("SKOLL_LMSTUDIO_API_MODE", "openai")
    monkeypatch.setenv("SKOLL_LMSTUDIO_TIMEOUT_SECONDS", "42")

    client = LMStudioClient.from_settings()
    try:
        assert client.base_url == "http://127.0.0.1:4321"
        assert client.api_key == "sk-lm-test:secret"
        assert client.api_mode == "openai"
        assert client.timeout_seconds == 42
    finally:
        # nothing async to close here that needs awaiting in a sync test;
        # the AsyncClient is GC'd. We do not make network calls.
        pass


# --------------------------------------------------------------------------- #
# list_models — both shapes
# --------------------------------------------------------------------------- #


@respx.mock
async def test_list_models_native_shape() -> None:
    payload = _load_fixture("models_list.json")
    respx.get(f"{BASE_URL}/api/v1/models").mock(return_value=httpx.Response(200, json=payload))
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        models = await client.list_models()

    ids = [m.id for m in models]
    assert ids == [
        "qwen2.5-coder-32b-instruct",
        "qwen3-coder-30b-a3b-instruct",
        "nomic-embed-text-v1.5",
    ]
    by_id = {m.id: m for m in models}
    # Native fields parsed.
    assert by_id["qwen2.5-coder-32b-instruct"].loaded_context_length == 16384
    assert by_id["qwen2.5-coder-32b-instruct"].max_context_length == 32768
    assert by_id["qwen2.5-coder-32b-instruct"].capabilities == ["tool_use"]
    # dict-shaped capabilities reduced to sorted list of enabled features.
    assert by_id["qwen3-coder-30b-a3b-instruct"].capabilities == ["reasoning", "tool_use"]
    # not-loaded embedding model has no loaded context length.
    assert by_id["nomic-embed-text-v1.5"].loaded_context_length is None
    assert by_id["nomic-embed-text-v1.5"].capabilities == ["embeddings"]


@respx.mock
async def test_list_models_openai_shape() -> None:
    payload = _load_fixture("models_list_openai.json")
    respx.get(f"{BASE_URL}/v1/models").mock(return_value=httpx.Response(200, json=payload))
    async with LMStudioClient(BASE_URL, api_mode="openai") as client:
        models = await client.list_models()

    ids = [m.id for m in models]
    assert ids == [
        "qwen2.5-coder-32b-instruct",
        "qwen3-coder-30b-a3b-instruct",
        "nomic-embed-text-v1.5",
    ]
    # openai-compat omits context lengths / capabilities.
    assert all(m.loaded_context_length is None for m in models)
    assert all(m.capabilities == [] for m in models)


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #


@respx.mock
async def test_chat_returns_content() -> None:
    payload = _load_fixture("chat_simple_nontool.json")
    route = respx.post(f"{BASE_URL}/api/v1/chat").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        response = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="qwen2.5-coder-32b-instruct",
        )

    assert route.called
    content = extract_assistant_content(response)
    assert content.startswith("Hello!")
    # Non-reasoning model: no reasoning switch added to the request.
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "qwen2.5-coder-32b-instruct"
    assert sent["stream"] is False
    assert "reasoning" not in sent


@respx.mock
async def test_chat_reasoning_model_sets_reasoning_off_native() -> None:
    payload = _load_fixture("chat_simple_nontool.json")
    route = respx.post(f"{BASE_URL}/api/v1/chat").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="qwen3-coder-30b-a3b-instruct",
        )
    sent = json.loads(route.calls.last.request.content)
    assert sent["reasoning"] == "off"


@respx.mock
async def test_chat_reasoning_off_openai_uses_reasoning_effort() -> None:
    payload = _load_fixture("chat_simple_nontool.json")
    route = respx.post(f"{BASE_URL}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with LMStudioClient(BASE_URL, api_mode="openai") as client:
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="some-model",
            reasoning_off=True,
        )
    sent = json.loads(route.calls.last.request.content)
    assert sent["reasoning_effort"] == "off"
    assert "reasoning" not in sent


@respx.mock
async def test_chat_4xx_raises_lmstudio_error() -> None:
    payload = _load_fixture("error_400_invalid_model.json")
    respx.post(f"{BASE_URL}/api/v1/chat").mock(return_value=httpx.Response(400, json=payload))
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        with pytest.raises(LMStudioError) as exc_info:
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="does-not-exist",
            )
    # The error carries the LM Studio body (its own text, not user content).
    assert "model_not_found" in str(exc_info.value)
    assert exc_info.value.code == "lmstudio.error"


@respx.mock
async def test_chat_401_raises_auth_error() -> None:
    respx.post(f"{BASE_URL}/api/v1/chat").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    async with LMStudioClient(BASE_URL, api_mode="native", api_key="sk-lm-x:y") as client:
        with pytest.raises(LMStudioAuthError):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="m",
            )


@respx.mock
async def test_5xx_is_retried_then_succeeds() -> None:
    payload = _load_fixture("models_list.json")
    route = respx.get(f"{BASE_URL}/api/v1/models")
    route.side_effect = [
        httpx.Response(503, text="overloaded"),
        httpx.Response(200, json=payload),
    ]
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        models = await client.list_models()
    assert len(models) == 3
    assert route.call_count == 2


# --------------------------------------------------------------------------- #
# SECURITY: Authorization header must never appear in logs or error text
# --------------------------------------------------------------------------- #


@respx.mock
async def test_auth_header_never_logged_on_error(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Realistic fake token; the assertions below prove it gets redacted.
    bearer_value = "sk-lm-supersecrettoken:abcdef0123456789"  # gitleaks:allow
    respx.post(f"{BASE_URL}/api/v1/chat").mock(return_value=httpx.Response(401, text="nope"))
    with caplog.at_level(logging.DEBUG):
        async with LMStudioClient(BASE_URL, api_mode="native", api_key=bearer_value) as client:
            with pytest.raises(LMStudioAuthError) as exc_info:
                await client.chat(
                    messages=[{"role": "user", "content": "hi"}],
                    model="m",
                )

    # The raw token must not leak into the exception text...
    assert bearer_value not in str(exc_info.value)
    # ...nor into any captured log record (stdlib-captured)...
    assert bearer_value not in caplog.text
    # ...nor into anything structlog wrote to stdout/stderr.
    captured = capsys.readouterr()
    assert bearer_value not in captured.out
    assert bearer_value not in captured.err


def test_auth_header_redacted_helper() -> None:
    from skoll.lm.client import _redact_headers

    bearer_value = "sk-lm-secret:token"
    redacted = _redact_headers({"Authorization": f"Bearer {bearer_value}", "Accept": "*/*"})
    assert bearer_value not in json.dumps(redacted)
    assert redacted["Authorization"] == "Bearer [REDACTED]"
    assert redacted["Accept"] == "*/*"
