"""Session CRUD + the streaming chat endpoint.

Issue: phase-1.1 (SSE messages endpoint), phase-1.15 (persistence — stubbed here).
Contracts: contracts/openapi.yaml, contracts/events.yaml.

POST /api/sessions                  → create a session, returns its id
POST /api/sessions/{id}/messages    → run the agent loop, stream SSE events

The session store here is a deliberately minimal in-memory dict (session_id → history).
Another agent is building the real DB-backed repository (Issue 1.15); this module does
NOT import skoll.db. The single seam to swap is ``_SESSIONS`` / the ``_store`` helpers
below — see the phase-1.15 TODO.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from skoll.agent.loop import AgentEvent, AgentLoop, AgentLoopConfig
from skoll.agent.tools.registry import ToolRegistry
from skoll.config import get_settings
from skoll.errors import LMStudioError
from skoll.lm.client import LMStudioClient

logger = structlog.get_logger(__name__)

router = APIRouter()

# Reject message bodies larger than 1 MB (same guard as POST /api/chat) before parsing.
_MAX_BODY_BYTES = 1 * 1024 * 1024

# Keep-alive ping cadence (seconds) — contracts/events.yaml documents 15s.
_PING_SECONDS = 15

# Phase enabled for the tool registry in Phase-1 (read-only tools only).
_ENABLED_PHASES: set[str] = {"1"}

# --------------------------------------------------------------------------- #
# In-memory session store — the ONLY phase-1.15 swap seam.
# TODO(phase-1.15): replace this dict with the SQLite-backed repo (skoll.db) the
#   persistence agent is building. Keep _load_history / _save_history as the seam so
#   callers below do not change. Do NOT import skoll.db here yet.
# --------------------------------------------------------------------------- #
_SESSIONS: dict[str, list[dict[str, Any]]] = {}


def _create_session() -> str:
    session_id = str(uuid.uuid4())
    _SESSIONS[session_id] = []
    return session_id


def _session_exists(session_id: str) -> bool:
    return session_id in _SESSIONS


def _load_history(session_id: str) -> list[dict[str, Any]]:
    return _SESSIONS[session_id]


def _append_user_message(session_id: str, content: str) -> None:
    _SESSIONS[session_id].append({"role": "user", "content": content})


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class CreateSessionResponse(BaseModel):
    id: str


class SendMessageRequest(BaseModel):
    """Body for POST /api/sessions/{id}/messages."""

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, StringConstraints(min_length=1)]
    model: str | None = None


# --------------------------------------------------------------------------- #
# Dependency construction (overridable in tests via monkeypatch)
# --------------------------------------------------------------------------- #


def _contracts_tools_dir() -> Path:
    """Absolute path to ``contracts/tools`` at the repo root.

    Resolved relative to this source file: src/skoll/api/sessions.py → repo root is
    ``parents[4]``. Avoids a config dependency the persistence agent has not added yet.
    """
    return Path(__file__).resolve().parents[4] / "contracts" / "tools"


def _build_tool_registry() -> ToolRegistry:
    """Load the Phase-1 (read-only) tool registry from contracts/tools."""
    return ToolRegistry.load_from_contracts(str(_contracts_tools_dir()), _ENABLED_PHASES)


async def _resolve_model(client: LMStudioClient, requested: str | None) -> str:
    """Pick the model: explicit request > configured default > first loaded model."""
    settings = get_settings()
    model = requested or settings.lmstudio.default_model
    if model:
        return model
    available = await client.list_models()
    if not available:
        raise LMStudioError("No model specified and no models are loaded in LM Studio.")
    return available[0].id


def _to_sse(event: AgentEvent) -> ServerSentEvent:
    """Serialize an AgentEvent to the SSE wire format `event: <name>\\ndata: <json>\\n\\n`.

    The JSON payload is compact (no spaces) so a single event stays on one ``data:`` line.
    """
    return ServerSentEvent(event=event.name, data=json.dumps(event.data, separators=(",", ":")))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.post("/sessions")
async def create_session() -> JSONResponse:
    """Create a new (empty) chat session.

    Returns 201 ``{"id": <uuid>}``. History is held in the in-memory store until the
    phase-1.15 DB repo replaces it.
    """
    session_id = _create_session()
    body = CreateSessionResponse(id=session_id)
    return JSONResponse(status_code=201, content=body.model_dump())


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, request: Request) -> Response:
    """Append a user message and stream the agent's response as SSE.

    Body: ``{"content": <str>, "model": <str|null>}``. On success returns an
    ``EventSourceResponse`` emitting the events in contracts/events.yaml; a keep-alive
    ``ping`` is sent every 15s. If the client disconnects, the agent loop is cancelled
    (``asyncio.CancelledError`` propagates out of the async generator).
    """
    if not _session_exists(session_id):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "session.not_found", "message": "Unknown session id."}},
        )

    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": {"code": "request.too_large", "message": "Request body exceeds 1 MB."}
            },
        )

    try:
        payload = SendMessageRequest.model_validate_json(raw)
    except ValidationError as exc:
        # Surface field locations + messages WITHOUT echoing submitted values.
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "request.invalid", "message": detail}},
        )

    _append_user_message(session_id, payload.content)

    generator = _event_stream(session_id, payload.model, request)
    return EventSourceResponse(generator, ping=_PING_SECONDS)


async def _event_stream(
    session_id: str,
    requested_model: str | None,
    request: Request,
) -> AsyncIterator[ServerSentEvent]:
    """Drive AgentLoop.run and yield ServerSentEvents until done or client disconnect.

    Owns the LM Studio client for the lifetime of the stream (closed in ``finally``).
    Any uncaught ``LMStudioError`` raised before the loop starts (e.g. model resolution
    against a down LM Studio) is surfaced as an ``error`` + ``message_end`` pair so the
    client always sees a terminal event rather than a silently dropped stream.
    """
    settings = get_settings()
    async with LMStudioClient.from_settings() as client:
        try:
            model = await _resolve_model(client, requested_model)
        except LMStudioError as exc:
            logger.warning("sessions.model_resolution_failed", code=exc.code)
            yield _to_sse(
                AgentEvent("error", {"code": exc.code, "message": str(exc), "recoverable": False})
            )
            yield _to_sse(AgentEvent("message_end", {"stop_reason": "error"}))
            return

        registry = _build_tool_registry()
        config = AgentLoopConfig(
            max_iterations=settings.agent.max_iterations,
            model=model,
            workspace_root=str(settings.workspace_root),
        )
        loop = AgentLoop(lm_client=client, tool_registry=registry, config=config)
        history = _load_history(session_id)

        async for event in loop.run(session_id, history):
            # If the client has gone away, stop driving the loop. EventSourceResponse
            # also detects disconnects, but checking here lets the generator unwind
            # promptly and release the LM Studio client.
            if await request.is_disconnected():
                logger.info("sessions.client_disconnected", session_id=session_id)
                break
            yield _to_sse(event)
