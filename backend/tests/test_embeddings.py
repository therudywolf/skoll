"""Tests for LM Studio embeddings (Issue 1.7).

LM Studio is mocked with respx — no network, no real server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import respx
import skoll.config as config_mod
from skoll.errors import LMStudioError
from skoll.lm.client import LMStudioClient
from skoll.rag.embeddings import embed_chunks

BASE_URL = "http://127.0.0.1:1234"
DIM = 4


def _embeddings_response(texts: list[str]) -> dict[str, Any]:
    """Build a deterministic embeddings payload: one DIM-vector per input."""
    data = []
    for i, _ in enumerate(texts):
        # Distinct, deterministic vector per index.
        vec = [float(i + 1), float(i + 1) * 0.5, 0.25, 0.0]
        data.append({"object": "embedding", "index": i, "embedding": vec})
    return {"object": "list", "data": data, "model": "nomic-embed-text-v1.5"}


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    config_mod._settings = None
    yield
    config_mod._settings = None


# --------------------------------------------------------------------------- #
# LMStudioClient.embed
# --------------------------------------------------------------------------- #


@respx.mock
async def test_embed_parses_native_response() -> None:
    def _responder(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response(body["input"]))

    route = respx.post(f"{BASE_URL}/api/v1/embeddings").mock(side_effect=_responder)
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        vectors = await client.embed(["alpha", "beta", "gamma"], model="nomic-embed-text-v1.5")

    assert route.called
    assert len(vectors) == 3
    assert all(len(v) == DIM for v in vectors)
    assert vectors[0] == [1.0, 0.5, 0.25, 0.0]
    assert vectors[2] == [3.0, 1.5, 0.25, 0.0]


@respx.mock
async def test_embed_openai_mode_hits_openai_path() -> None:
    def _responder(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response(body["input"]))

    route = respx.post(f"{BASE_URL}/v1/embeddings").mock(side_effect=_responder)
    async with LMStudioClient(BASE_URL, api_mode="openai") as client:
        vectors = await client.embed(["one"], model="m")

    assert route.called
    assert len(vectors) == 1


async def test_embed_empty_returns_empty() -> None:
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        assert await client.embed([], model="m") == []


@respx.mock
async def test_embed_size_mismatch_raises() -> None:
    # Server returns fewer vectors than requested.
    respx.post(f"{BASE_URL}/api/v1/embeddings").mock(
        return_value=httpx.Response(200, json=_embeddings_response(["only-one"]))
    )
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        with pytest.raises(LMStudioError, match="batch size mismatch"):
            await client.embed(["a", "b"], model="m")


@respx.mock
async def test_embed_missing_data_array_raises() -> None:
    respx.post(f"{BASE_URL}/api/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"object": "list"})
    )
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        with pytest.raises(LMStudioError, match="missing a 'data' array"):
            await client.embed(["a"], model="m")


@respx.mock
async def test_embed_batches_large_input() -> None:
    # 70 inputs with batch_size=32 -> 3 POSTs.
    def _responder(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response(body["input"]))

    route = respx.post(f"{BASE_URL}/api/v1/embeddings").mock(side_effect=_responder)
    async with LMStudioClient(BASE_URL, api_mode="native") as client:
        vectors = await client.embed([f"t{i}" for i in range(70)], model="m")

    assert len(vectors) == 70
    assert route.call_count == 3


# --------------------------------------------------------------------------- #
# embed_chunks
# --------------------------------------------------------------------------- #


@respx.mock
async def test_embed_chunks_returns_n_by_dim_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_LMSTUDIO_BASE_URL", BASE_URL)
    monkeypatch.setenv("SKOLL_LMSTUDIO_API_MODE", "native")

    def _responder(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response(body["input"]))

    respx.post(f"{BASE_URL}/api/v1/embeddings").mock(side_effect=_responder)

    arr = await embed_chunks(["a", "b", "c"], model="nomic-embed-text-v1.5")
    assert isinstance(arr, np.ndarray)
    assert arr.shape == (3, DIM)
    assert arr.dtype == np.float32


async def test_embed_chunks_empty_returns_empty_array() -> None:
    arr = await embed_chunks([], model="m")
    assert arr.shape == (0, 0)
    assert arr.dtype == np.float32


@respx.mock
async def test_embed_chunks_uses_disk_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SKOLL_LMSTUDIO_BASE_URL", BASE_URL)
    monkeypatch.setenv("SKOLL_LMSTUDIO_API_MODE", "native")

    def _responder(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        return httpx.Response(200, json=_embeddings_response(body["input"]))

    route = respx.post(f"{BASE_URL}/api/v1/embeddings").mock(side_effect=_responder)
    cache = str(tmp_path / "emb_cache")

    first = await embed_chunks(["x", "y"], model="m", cache_dir=cache)
    calls_after_first = route.call_count
    # Second run with identical inputs should be served entirely from cache.
    second = await embed_chunks(["x", "y"], model="m", cache_dir=cache)

    assert route.call_count == calls_after_first  # no new network calls
    assert np.array_equal(first, second)
