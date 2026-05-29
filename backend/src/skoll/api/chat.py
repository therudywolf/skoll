"""Chat endpoints — POST /api/sessions/{id}/messages returns SSE stream.

Issue: phase-0.4 (non-streaming), phase-1.1 (SSE).
Contracts: contracts/openapi.yaml, contracts/events.yaml.

NOTE: POST /chat below is a *dev convenience* endpoint. It is deliberately NOT part of
contracts/openapi.yaml — the canonical chat surface is the SSE endpoint added in 1.1.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from skoll.config import get_settings
from skoll.errors import LMStudioError
from skoll.lm.client import LMStudioClient, extract_assistant_content

logger = structlog.get_logger(__name__)

router = APIRouter()

# Reject bodies larger than 1 MB (Issue 0.4 security note) before we even parse them.
_MAX_BODY_BYTES = 1 * 1024 * 1024


class ChatMessage(BaseModel):
    """One chat message. Extra fields rejected to keep the contract tight."""

    model_config = ConfigDict(extra="forbid")

    role: Annotated[str, StringConstraints(min_length=1)]
    content: str


class ChatRequest(BaseModel):
    """POST /api/chat request body.

    ``extra="forbid"`` so unknown top-level keys are a 4xx, not silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None


class ChatResponse(BaseModel):
    """POST /api/chat success body."""

    content: str
    model: str


def _error_response(exc: LMStudioError, status_code: int = 400) -> JSONResponse:
    """Build the ``{"error": {"code", "message"}}`` envelope from an LMStudioError.

    The message comes from the exception (LM Studio's own text / our static strings) and
    NEVER echoes user-supplied content — a leak vector called out in Issue 0.4.
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": exc.code, "message": str(exc)}},
    )


@router.post("/chat")
async def chat(request: Request) -> JSONResponse:
    """Non-streaming chat completion (dev convenience).

    Body: ``{"messages": [{"role": ..., "content": ...}], "model": <str|null>}``.
    On success returns 200 ``{"content": <assistant text>, "model": <model id used>}``.
    On a bad model / LM Studio failure returns 400 ``{"error": {"code", "message"}}``.
    """
    # --- 1 MB body guard (before parsing) ---
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return _error_response(
            LMStudioError("Request body exceeds the 1 MB limit."),
            status_code=413,
        )

    # --- validate body ---
    try:
        payload = ChatRequest.model_validate_json(raw)
    except ValidationError as exc:
        # Surface field locations + messages WITHOUT echoing submitted values: we read
        # only e["loc"] and e["msg"], never e["input"] (which would leak user content).
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "request.invalid", "message": detail}},
        )

    settings = get_settings()

    async with LMStudioClient.from_settings() as client:
        # Resolve the model: explicit > configured default > first available.
        model = payload.model or settings.lmstudio.default_model
        if not model:
            try:
                available = await client.list_models()
            except LMStudioError as exc:
                logger.warning("chat.list_models_failed", code=exc.code)
                return _error_response(exc)
            if not available:
                return _error_response(
                    LMStudioError("No model specified and no models are loaded."),
                )
            model = available[0].id

        messages = [m.model_dump() for m in payload.messages]
        try:
            response = await client.chat(messages=messages, model=model)
        except LMStudioError as exc:
            # Bad model id, payload mismatch, auth, unreachable — all map to a 400 with
            # the error shape. Never include user content in the message.
            logger.warning("chat.completion_failed", code=exc.code, model=model)
            return _error_response(exc)

    content = extract_assistant_content(response)
    body = ChatResponse(content=content, model=model)
    return JSONResponse(status_code=200, content=body.model_dump())


# TODO(phase-1.1): POST /sessions/{session_id}/messages → EventSourceResponse
#   Body: SendMessageRequest (see openapi.yaml)
#   Drives skoll.agent.loop.AgentLoop.run(session_id, history)
#   Converts AgentEvent → SSE wire format
#   Emits ping every 15s via background task
#   On client disconnect: abort the agent loop (asyncio.CancelledError propagates)
