"""Tests for GET /api/health (Issue 0.2).

LM Studio is mocked via respx — no real server, and the probe must never hang.
"""

from __future__ import annotations

import asyncio
import time
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


def _models_payload() -> dict[str, Any]:
    import json

    path = Path(__file__).parent / "fixtures" / "lm_studio" / "models_list.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def _get_health() -> httpx.Response:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/health")


@respx.mock
async def test_health_schema_and_reachable_true() -> None:
    respx.get(f"{LM_BASE}/api/v1/models").mock(
        return_value=httpx.Response(200, json=_models_payload())
    )
    resp = await _get_health()
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok",
        "version": "0.1.0a0",
        "lm_studio_reachable": True,
    }


@respx.mock
async def test_health_reachable_false_when_probe_fails() -> None:
    respx.get(f"{LM_BASE}/api/v1/models").mock(side_effect=httpx.ConnectError("connection refused"))
    resp = await _get_health()
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0a0"
    assert body["lm_studio_reachable"] is False


@respx.mock
async def test_health_does_not_hang_when_lm_studio_slow() -> None:
    async def _slow(_request: httpx.Request) -> httpx.Response:
        # Simulate a hung LM Studio: take far longer than the 1s probe budget.
        await asyncio.sleep(5.0)
        return httpx.Response(200, json=_models_payload())

    respx.get(f"{LM_BASE}/api/v1/models").mock(side_effect=_slow)

    start = time.perf_counter()
    resp = await _get_health()
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    assert resp.json()["lm_studio_reachable"] is False
    # The 1s probe deadline must bound the call well under the 5s fake delay.
    assert elapsed < 3.0


@respx.mock
async def test_health_reachable_false_on_5xx() -> None:
    # Persisting 5xx exhausts retries → reported as unreachable, never raised.
    respx.get(f"{LM_BASE}/api/v1/models").mock(return_value=httpx.Response(500, text="boom"))
    resp = await _get_health()
    assert resp.status_code == 200
    assert resp.json()["lm_studio_reachable"] is False
