"""Chat endpoints — POST /api/sessions/{id}/messages returns SSE stream.

Issue: phase-0.4 (non-streaming), phase-1.1 (SSE).
Contracts: contracts/openapi.yaml, contracts/events.yaml.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# TODO(phase-0.4): POST /chat (non-streaming, dev convenience)
# TODO(phase-1.1): POST /sessions/{session_id}/messages → EventSourceResponse
#   Body: SendMessageRequest (see openapi.yaml)
#   Drives skoll.agent.loop.AgentLoop.run(session_id, history)
#   Converts AgentEvent → SSE wire format
#   Emits ping every 15s via background task
#   On client disconnect: abort the agent loop (asyncio.CancelledError propagates)
