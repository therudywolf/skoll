"""Tests for the SSE messages endpoint (Issue 1.1).

FastAPI TestClient hits POST /api/sessions then POST /api/sessions/{id}/messages. The LM
client and AgentLoop are faked so no real LM Studio is touched — we assert the SSE wire
format (`event: <name>` / `data: <json>` framing) and the event sequence the agent loop
produces, plus the create/404/validation paths.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
import skoll.api.sessions as sessions_mod
import skoll.config as config_mod
from fastapi.testclient import TestClient
from skoll.agent.loop import AgentEvent
from skoll.app import create_app


@pytest.fixture(autouse=True)
def _reset_settings_and_store() -> Any:
    config_mod._settings = None
    sessions_mod._SESSIONS.clear()
    _reset_sse_app_status()
    yield
    config_mod._settings = None
    sessions_mod._SESSIONS.clear()
    _reset_sse_app_status()


def _reset_sse_app_status() -> None:
    """Clear sse-starlette's process-global shutdown Event between tests.

    The sync TestClient spins up a fresh asyncio loop per request; sse-starlette caches
    ``AppStatus.should_exit_event`` on the first loop it sees, so a later test reusing the
    cached Event hits 'bound to a different event loop'. Resetting it to None forces a fresh
    Event per test. (Production runs one loop, so this is purely a test-harness concern.)
    """
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    AppStatus.should_exit = False


# --------------------------------------------------------------------------- #
# Fakes wired in via monkeypatch
# --------------------------------------------------------------------------- #


class _FakeModel:
    id = "qwen2.5-coder-32b"


class _FakeClient:
    """Stands in for LMStudioClient as an async context manager."""

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_models(self) -> list[_FakeModel]:
        return [_FakeModel()]


class _FakeLoop:
    """Yields a scripted list of AgentEvents from .run()."""

    script: ClassVar[list[AgentEvent]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def run(
        self, session_id: str, history: list[dict[str, Any]]
    ) -> AsyncIterator[AgentEvent]:
        for event in type(self).script:
            yield event


def _install_fakes(monkeypatch: pytest.MonkeyPatch, script: list[AgentEvent]) -> None:
    monkeypatch.setattr(
        sessions_mod.LMStudioClient, "from_settings", classmethod(lambda cls: _FakeClient())
    )
    monkeypatch.setattr(sessions_mod, "_build_tool_registry", lambda: object())
    _FakeLoop.script = script
    monkeypatch.setattr(sessions_mod, "AgentLoop", _FakeLoop)


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into (event_name, data_dict) pairs, ignoring pings/comments."""
    events: list[tuple[str, dict[str, Any]]] = []
    event_name: str | None = None
    data_lines: list[str] = []
    for raw in body.split("\n"):
        line = raw.rstrip("\r")
        if line == "":
            if event_name is not None and data_lines:
                events.append((event_name, json.loads("\n".join(data_lines))))
            event_name, data_lines = None, []
            continue
        if line.startswith(":"):
            continue  # comment / keep-alive ping
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    return events


# --------------------------------------------------------------------------- #
# POST /api/sessions
# --------------------------------------------------------------------------- #


def test_create_session_returns_id() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/sessions")
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id"}
    assert isinstance(body["id"], str) and body["id"]
    # The new session is registered in the store.
    assert body["id"] in sessions_mod._SESSIONS


# --------------------------------------------------------------------------- #
# POST /api/sessions/{id}/messages — happy path SSE
# --------------------------------------------------------------------------- #


def test_messages_streams_events_in_wire_format(monkeypatch: pytest.MonkeyPatch) -> None:
    script = [
        AgentEvent("message_start", {"message_id": "m1", "role": "assistant"}),
        AgentEvent("text_delta", {"delta": "Hello"}),
        AgentEvent("message_end", {"stop_reason": "end_of_turn"}),
    ]
    _install_fakes(monkeypatch, script)

    client = TestClient(create_app())
    session_id = client.post("/api/sessions").json()["id"]

    resp = client.post(f"/api/sessions/{session_id}/messages", json={"content": "hi"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    parsed = _parse_sse(resp.text)
    assert parsed == [
        ("message_start", {"message_id": "m1", "role": "assistant"}),
        ("text_delta", {"delta": "Hello"}),
        ("message_end", {"stop_reason": "end_of_turn"}),
    ]

    # The raw wire framing uses `event: <name>` then `data: <json>`.
    assert "event: text_delta" in resp.text
    assert 'data: {"delta":"Hello"}' in resp.text

    # The user message was appended to the in-memory history.
    history = sessions_mod._SESSIONS[session_id]
    assert history[0] == {"role": "user", "content": "hi"}


def test_messages_tool_call_event_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    script = [
        AgentEvent("message_start", {"message_id": "m1", "role": "assistant"}),
        AgentEvent("tool_call_start", {"tool_call_id": "c1", "name": "codebase_search"}),
        AgentEvent(
            "tool_call_ready",
            {
                "tool_call_id": "c1",
                "name": "codebase_search",
                "arguments": {"query": "auth"},
                "requires_approval": False,
            },
        ),
        AgentEvent("tool_call_approved", {"tool_call_id": "c1", "by": "auto", "edited": False}),
        AgentEvent(
            "tool_call_result",
            {
                "tool_call_id": "c1",
                "status": "completed",
                "result": {"hits": []},
                "error": None,
                "duration_ms": 3,
            },
        ),
        AgentEvent("message_end", {"stop_reason": "end_of_turn"}),
    ]
    _install_fakes(monkeypatch, script)

    client = TestClient(create_app())
    session_id = client.post("/api/sessions").json()["id"]
    resp = client.post(f"/api/sessions/{session_id}/messages", json={"content": "where is auth?"})

    names = [name for name, _ in _parse_sse(resp.text)]
    assert names == [
        "message_start",
        "tool_call_start",
        "tool_call_ready",
        "tool_call_approved",
        "tool_call_result",
        "message_end",
    ]


# --------------------------------------------------------------------------- #
# Error / validation paths
# --------------------------------------------------------------------------- #


def test_messages_unknown_session_returns_404() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/sessions/does-not-exist/messages", json={"content": "hi"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "session.not_found"


def test_messages_rejects_empty_content() -> None:
    client = TestClient(create_app())
    session_id = client.post("/api/sessions").json()["id"]
    resp = client.post(f"/api/sessions/{session_id}/messages", json={"content": ""})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request.invalid"


def test_messages_rejects_extra_fields() -> None:
    client = TestClient(create_app())
    session_id = client.post("/api/sessions").json()["id"]
    resp = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "hi", "bogus": 1},
    )
    assert resp.status_code == 422


def test_messages_model_resolution_failure_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A client whose list_models raises (no model configured) → error + message_end(error).
    from skoll.errors import LMStudioUnreachableError

    class _DownClient(_FakeClient):
        async def list_models(self) -> list[_FakeModel]:
            raise LMStudioUnreachableError("LM Studio is unreachable")

    monkeypatch.setattr(
        sessions_mod.LMStudioClient, "from_settings", classmethod(lambda cls: _DownClient())
    )
    monkeypatch.setattr(sessions_mod, "_build_tool_registry", lambda: object())

    client = TestClient(create_app())
    session_id = client.post("/api/sessions").json()["id"]
    resp = client.post(f"/api/sessions/{session_id}/messages", json={"content": "hi"})
    assert resp.status_code == 200

    parsed = _parse_sse(resp.text)
    names = [n for n, _ in parsed]
    assert names == ["error", "message_end"]
    assert parsed[0][1]["code"] == "lmstudio.unreachable"
    assert parsed[1][1] == {"stop_reason": "error"}
