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

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import ToolRegistry
    from skoll.lm.client import LMStudioClient


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

    Yields AgentEvent objects. Caller (api/chat.py) converts to SSE wire format.
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
        """Drive the loop. See contracts/events.yaml for emitted event names.

        Implementation outline (phase-1.4 minimum):
          - Loop while iteration < max_iterations:
              - Call self.lm.chat_stream(messages=history, tools=self.tools.openai_schemas())
              - For each delta from the stream:
                  - emit text_delta / tool_call_* events
                  - accumulate assembled message
              - Append assistant message to history
              - If no tool_calls → emit message_end, break
              - For each tool_call:
                  - preflight (raises → tool_call_result with status=failed)
                  - if requires_approval: await human (out of loop scope; api/chat.py handles)
                  - execute via self.tools.execute(name, args)
                  - append tool result to history
          - On max_iterations: emit error event
        """
        # TODO(phase-1.4)
        raise NotImplementedError
        yield  # pragma: no cover
