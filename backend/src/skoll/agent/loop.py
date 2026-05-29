"""Agent ReAct loop.

Issue: phase-1.4 (read-only tools), expanded in phase-2.

The loop is responsible for:
  1. Call LM Studio (streaming) with current history + tool schemas
  2. As deltas arrive, emit SSE events to the client
  3. Accumulate tool_call args until JSON parses
  4. Run preflight checks on each tool call (path validation, secrets, etc.)
  5. Gate write/exec tools behind human approval
  6. Execute tool, append result to history, repeat
  7. Stop on: final text-only message, max_iterations, error, user reject

See docs/ARCHITECTURE.md §3 for the full pseudocode.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from skoll.agent.streaming import StreamingToolCall, ToolCallAccumulator
from skoll.agent.tools.registry import ToolContext
from skoll.errors import LMStudioError, ToolError

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolRegistry
    from skoll.lm.client import ChatCompletionDelta, LMStudioClient

logger = structlog.get_logger(__name__)


@dataclass
class AgentLoopConfig:
    max_iterations: int
    model: str
    workspace_root: str


@dataclass
class AgentEvent:
    """One SSE event to be emitted to the client. See contracts/events.yaml."""

    name: str
    data: dict[str, Any]


class AgentLoop:
    """Runs one user message through up to N iterations of think-act-observe.

    Yields AgentEvent objects. Caller (api/sessions.py) converts to SSE wire format.
    """

    def __init__(
        self,
        lm_client: LMStudioClient,
        tool_registry: ToolRegistry,
        config: AgentLoopConfig,
    ) -> None:
        self.lm = lm_client
        self.tools = tool_registry
        self.config = config

    async def run(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> AsyncIterator[AgentEvent]:
        """Drive the loop. Emits events whose names match contracts/events.yaml exactly.

        Per iteration:
          - stream a completion (``message_start`` then ``text_delta`` / ``tool_call_*``)
          - append the assembled assistant message to ``history``
          - if the model called no tools → ``message_end`` (end_of_turn) and stop
          - otherwise, for each fully-parsed tool call:
              * Phase-1 read-only tool (``requires_approval=false``): emit ``tool_call_ready``
                (requires_approval=false) + ``tool_call_approved`` (by=auto), execute it,
                emit ``tool_call_result``, append the result to ``history``
              * tool that requires approval: emit ``tool_call_ready`` (requires_approval=true)
                and stop with ``message_end`` (tool_rejection) — see the phase-2.5 TODO; we
                never block the loop waiting for a human here.
          - if ``max_iterations`` is reached without a final answer → ``error`` +
            ``message_end`` (max_iterations).
        """
        context = ToolContext(session_id=session_id, workspace_root=self.config.workspace_root)

        for _iteration in range(self.config.max_iterations):
            message_id = str(uuid.uuid4())
            yield AgentEvent("message_start", {"message_id": message_id, "role": "assistant"})

            accumulator = ToolCallAccumulator()
            text_parts: list[str] = []
            # Names already announced via tool_call_start, keyed by streaming index.
            started_indices: set[int] = set()

            try:
                async for delta in self.lm.chat_stream(
                    messages=history,
                    model=self.config.model,
                    tools=self.tools.openai_schemas() or None,
                ):
                    if delta.text_delta:
                        text_parts.append(delta.text_delta)
                        yield AgentEvent("text_delta", {"delta": delta.text_delta})

                    if delta.tool_call_index is not None:
                        async for event in self._absorb_tool_delta(
                            accumulator, started_indices, delta.tool_call_index, delta
                        ):
                            yield event
            except LMStudioError as exc:
                # Stream failure (incl. mid-stream disconnect). Recoverable=False: in
                # Phase-1 we surface and end the turn rather than auto-reconnecting.
                logger.warning("agent.stream_failed", code=exc.code, session_id=session_id)
                yield AgentEvent(
                    "error", {"code": exc.code, "message": str(exc), "recoverable": False}
                )
                yield AgentEvent("message_end", {"stop_reason": "error"})
                return

            completed = accumulator.completed()
            assistant_message = _build_assistant_message("".join(text_parts), completed)
            history.append(assistant_message)

            if not completed:
                # Text-only turn → final answer.
                yield AgentEvent("message_end", {"stop_reason": "end_of_turn"})
                return

            # Act on each tool call. If any needs human approval, Phase-1 stops the turn.
            stop_for_approval = False
            for call in completed:
                async for event in self._handle_tool_call(call, context, history):
                    yield event
                    if event.name == "tool_call_ready" and event.data.get("requires_approval"):
                        stop_for_approval = True

            if stop_for_approval:
                # TODO(phase-2.5): instead of stopping, await human approval out-of-band
                #   (api layer resumes the loop on POST /tool-calls/{id}/approve) and then
                #   execute the approved call. For now Phase-1 ships read-only tools only,
                #   so a write/exec tool ends the turn with a tool_rejection stop reason.
                yield AgentEvent("message_end", {"stop_reason": "tool_rejection"})
                return

            # Otherwise loop again with the tool results appended to history.

        # Fell out of the loop without a final text answer.
        logger.info("agent.max_iterations", session_id=session_id, max=self.config.max_iterations)
        yield AgentEvent(
            "error",
            {
                "code": "agent.max_iterations",
                "message": f"Agent stopped after {self.config.max_iterations} iterations.",
                "recoverable": False,
            },
        )
        yield AgentEvent("message_end", {"stop_reason": "max_iterations"})

    async def _absorb_tool_delta(
        self,
        accumulator: ToolCallAccumulator,
        started_indices: set[int],
        index: int,
        delta: ChatCompletionDelta,
    ) -> AsyncIterator[AgentEvent]:
        """Absorb one streaming tool-call fragment and emit start/args-delta events.

        ``tool_call_start`` is emitted once per call, the first time both its ``id`` and
        ``name`` are known. ``tool_call_args_delta`` is emitted for every argument fragment
        (keyed by the call's id) so the client can render args as they stream.
        """
        accumulator.absorb_delta(
            index=index,
            call_id=delta.tool_call_id,
            name=delta.tool_call_name,
            args_delta=delta.tool_call_args_delta,
        )
        call = accumulator.calls[index]

        if index not in started_indices and call.id is not None and call.name is not None:
            started_indices.add(index)
            yield AgentEvent("tool_call_start", {"tool_call_id": call.id, "name": call.name})

        if delta.tool_call_args_delta and call.id is not None:
            yield AgentEvent(
                "tool_call_args_delta",
                {"tool_call_id": call.id, "args_delta": delta.tool_call_args_delta},
            )

    async def _handle_tool_call(
        self,
        call: StreamingToolCall,
        context: ToolContext,
        history: list[dict[str, Any]],
    ) -> AsyncIterator[AgentEvent]:
        """Emit ready/approval/result events for one completed tool call.

        Read-only tools (``requires_approval=false``) auto-approve and execute inline; the
        tool result is appended to ``history`` so the next iteration can observe it. A tool
        that requires approval emits only ``tool_call_ready`` (requires_approval=true) and
        returns — the caller stops the turn (Phase-1) or resumes it after approval (Phase-2.5).
        """
        # `call` came from accumulator.completed(), so id/name/args are all present.
        call_id = call.id
        name = call.name
        arguments = call.try_parse_args()
        assert call_id is not None and name is not None and arguments is not None

        requires_approval = self._requires_approval(name)
        yield AgentEvent(
            "tool_call_ready",
            {
                "tool_call_id": call_id,
                "name": name,
                "arguments": arguments,
                "requires_approval": requires_approval,
            },
        )

        if requires_approval:
            # Phase-1: do not execute; the caller ends the turn. (phase-2.5: await human.)
            return

        # Auto-approve read-only tools.
        yield AgentEvent(
            "tool_call_approved", {"tool_call_id": call_id, "by": "auto", "edited": False}
        )

        start = time.perf_counter()
        try:
            result = await self.tools.execute(name, arguments, context)
        except ToolError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning("agent.tool_failed", tool=name, code=exc.code)
            yield AgentEvent(
                "tool_call_result",
                {
                    "tool_call_id": call_id,
                    "status": "failed",
                    "result": None,
                    "error": str(exc),
                    "duration_ms": duration_ms,
                },
            )
            history.append(_tool_result_message(call_id, name, {"error": str(exc)}))
            return

        duration_ms = int((time.perf_counter() - start) * 1000)
        yield AgentEvent(
            "tool_call_result",
            {
                "tool_call_id": call_id,
                "status": "completed",
                "result": result,
                "error": None,
                "duration_ms": duration_ms,
            },
        )
        history.append(_tool_result_message(call_id, name, result))

    def _requires_approval(self, name: str) -> bool:
        """Whether a tool needs human approval before execution.

        Sourced from the tool's contract (``requires_approval`` in contracts/tools/*.json).
        An unknown tool name is treated as approval-required (fail-safe) rather than letting
        it auto-execute. Phase-1 only registers read-only tools, so this normally returns
        ``False``.
        """
        try:
            return self.tools.get(name).schema.requires_approval
        except ToolError:
            return True


def _build_assistant_message(
    text: str,
    tool_calls: list[StreamingToolCall],
) -> dict[str, Any]:
    """Assemble the assistant message to append to history (openai tool-call shape).

    Includes ``tool_calls`` (with re-serialized argument JSON) only when present, so a
    text-only turn appends a plain ``{"role": "assistant", "content": ...}`` message.
    """
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.try_parse_args() or {}),
                },
            }
            for call in tool_calls
        ]
    return message


def _tool_result_message(
    tool_call_id: str,
    name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``role: tool`` history entry the model reads on the next iteration."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": json.dumps(result),
    }
