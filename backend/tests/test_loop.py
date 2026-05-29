"""Tests for the agent ReAct loop (Issue 1.4).

No real LM Studio: a fake ``chat_stream`` yields scripted ``ChatCompletionDelta``s, and a
fake tool registry stands in for ``ToolRegistry``. We assert the emitted ``AgentEvent``
names/payloads match contracts/events.yaml for:
  - a text-only turn,
  - a read-only tool-call turn (auto-approve → execute → result → final answer),
  - the max_iterations path,
  - an approval-required tool (Phase-1 stops with tool_rejection),
  - a tool that raises (tool_call_result status=failed).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from skoll.agent.loop import AgentEvent, AgentLoop, AgentLoopConfig
from skoll.lm.client import ChatCompletionDelta

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _text(delta: str, finish: str | None = None) -> ChatCompletionDelta:
    return ChatCompletionDelta(
        text_delta=delta,
        tool_call_index=None,
        tool_call_id=None,
        tool_call_name=None,
        tool_call_args_delta=None,
        finish_reason=finish,
    )


def _tc(
    *,
    index: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    args_delta: str | None = None,
    finish: str | None = None,
) -> ChatCompletionDelta:
    return ChatCompletionDelta(
        text_delta=None,
        tool_call_index=index,
        tool_call_id=call_id,
        tool_call_name=name,
        tool_call_args_delta=args_delta,
        finish_reason=finish,
    )


class FakeLM:
    """Replays a list of scripted turns; each turn is a list of ChatCompletionDelta."""

    def __init__(self, turns: list[list[ChatCompletionDelta]]) -> None:
        self._turns = list(turns)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        reasoning_off: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[ChatCompletionDelta]:
        # Snapshot the history the loop passed in (for assertions on tool-result feedback).
        self.calls.append([dict(m) for m in messages])
        if not self._turns:
            raise AssertionError("FakeLM ran out of scripted turns")
        turn = self._turns.pop(0)
        for delta in turn:
            yield delta


@dataclass
class _FakeSchema:
    name: str
    description: str
    requires_approval: bool


@dataclass
class _FakeTool:
    schema: _FakeSchema


class FakeRegistry:
    """Minimal stand-in for ToolRegistry used by AgentLoop."""

    def __init__(
        self,
        tools: dict[str, bool],  # name -> requires_approval
        results: dict[str, dict[str, Any]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._tools = tools
        self._results = results or {}
        self._errors = errors or {}
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {"name": name, "description": name, "parameters": {"type": "object"}},
            }
            for name in sorted(self._tools)
        ]

    def get(self, name: str) -> _FakeTool:
        from skoll.errors import ToolError

        if name not in self._tools:
            raise ToolError(f"unknown tool: {name!r}")
        return _FakeTool(schema=_FakeSchema(name, name, self._tools[name]))

    async def execute(self, name: str, args: dict[str, Any], context: Any) -> dict[str, Any]:
        self.executed.append((name, args))
        if name in self._errors:
            raise self._errors[name]
        return self._results.get(name, {"ok": True})


def _config(max_iterations: int = 5) -> AgentLoopConfig:
    return AgentLoopConfig(
        max_iterations=max_iterations, model="qwen2.5-coder-32b", workspace_root="ws"
    )


async def _drain(loop: AgentLoop, history: list[dict[str, Any]]) -> list[AgentEvent]:
    return [e async for e in loop.run("sess-1", history)]


# --------------------------------------------------------------------------- #
# Text-only turn
# --------------------------------------------------------------------------- #


async def test_text_only_turn() -> None:
    lm = FakeLM([[_text("Hello"), _text(" world", finish="stop")]])
    registry = FakeRegistry(tools={})
    loop = AgentLoop(lm, registry, _config())  # type: ignore[arg-type]

    history: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
    events = await _drain(loop, history)

    names = [e.name for e in events]
    assert names == ["message_start", "text_delta", "text_delta", "message_end"]

    start = events[0]
    assert start.data["role"] == "assistant"
    assert isinstance(start.data["message_id"], str) and start.data["message_id"]

    assert events[1].data == {"delta": "Hello"}
    assert events[2].data == {"delta": " world"}
    assert events[-1].data == {"stop_reason": "end_of_turn"}

    # Assistant message appended to history (text only, no tool_calls).
    assert history[-1] == {"role": "assistant", "content": "Hello world"}


# --------------------------------------------------------------------------- #
# Read-only tool-call turn → auto-approve, execute, then a final answer
# --------------------------------------------------------------------------- #


async def test_read_only_tool_call_then_final_answer() -> None:
    turn_1 = [
        _tc(index=0, call_id="call_1", name="codebase_search"),
        _tc(index=0, args_delta='{"query": '),
        _tc(index=0, args_delta='"login"}', finish="tool_calls"),
    ]
    turn_2 = [_text("Found it in auth.py.", finish="stop")]
    lm = FakeLM([turn_1, turn_2])
    registry = FakeRegistry(
        tools={"codebase_search": False},
        results={"codebase_search": {"hits": ["auth.py:42"]}},
    )
    loop = AgentLoop(lm, registry, _config())  # type: ignore[arg-type]

    history: list[dict[str, Any]] = [{"role": "user", "content": "where is login?"}]
    events = await _drain(loop, history)
    names = [e.name for e in events]

    assert names == [
        "message_start",
        "tool_call_start",
        "tool_call_args_delta",
        "tool_call_args_delta",
        "tool_call_ready",
        "tool_call_approved",
        "tool_call_result",
        "message_start",
        "text_delta",
        "message_end",
    ]

    by_name = {e.name: e for e in events}
    assert by_name["tool_call_start"].data == {"tool_call_id": "call_1", "name": "codebase_search"}

    ready = by_name["tool_call_ready"].data
    assert ready["tool_call_id"] == "call_1"
    assert ready["name"] == "codebase_search"
    assert ready["arguments"] == {"query": "login"}
    assert ready["requires_approval"] is False

    approved = by_name["tool_call_approved"].data
    assert approved["tool_call_id"] == "call_1"
    assert approved["by"] == "auto"

    result = by_name["tool_call_result"].data
    assert result["tool_call_id"] == "call_1"
    assert result["status"] == "completed"
    assert result["result"] == {"hits": ["auth.py:42"]}
    assert result["error"] is None
    assert isinstance(result["duration_ms"], int)

    assert by_name["message_end"].data == {"stop_reason": "end_of_turn"}

    # The tool was actually executed with the parsed args.
    assert registry.executed == [("codebase_search", {"query": "login"})]

    # History: user, assistant(with tool_calls), tool result, assistant(final).
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["tool_calls"][0]["function"]["name"] == "codebase_search"
    assert history[2]["role"] == "tool"
    assert history[2]["tool_call_id"] == "call_1"
    assert '"hits"' in history[2]["content"]
    assert history[3] == {"role": "assistant", "content": "Found it in auth.py."}

    # Second LM call saw the tool result in its messages.
    assert any(m["role"] == "tool" for m in lm.calls[1])


async def test_args_delta_only_emitted_for_arg_fragments() -> None:
    # The chunk carrying id+name with no args must NOT emit a tool_call_args_delta.
    turn_1 = [
        _tc(index=0, call_id="c", name="codebase_search"),  # no args here
        _tc(index=0, args_delta='{"query":"x"}', finish="tool_calls"),
    ]
    lm = FakeLM([turn_1, [_text("done", finish="stop")]])
    registry = FakeRegistry(tools={"codebase_search": False})
    loop = AgentLoop(lm, registry, _config())  # type: ignore[arg-type]

    events = await _drain(loop, [{"role": "user", "content": "hi"}])
    args_deltas = [e for e in events if e.name == "tool_call_args_delta"]
    assert len(args_deltas) == 1
    assert args_deltas[0].data == {"tool_call_id": "c", "args_delta": '{"query":"x"}'}


# --------------------------------------------------------------------------- #
# max_iterations path
# --------------------------------------------------------------------------- #


async def test_max_iterations_emits_error_and_message_end() -> None:
    # Every turn calls a (read-only) tool, so the loop never reaches a final answer.
    def _tool_turn() -> list[ChatCompletionDelta]:
        return [
            _tc(
                index=0,
                call_id="c",
                name="codebase_search",
                args_delta='{"query":"x"}',
                finish="tool_calls",
            ),
        ]

    lm = FakeLM([_tool_turn(), _tool_turn()])
    registry = FakeRegistry(tools={"codebase_search": False})
    loop = AgentLoop(lm, registry, _config(max_iterations=2))  # type: ignore[arg-type]

    events = await _drain(loop, [{"role": "user", "content": "loop forever"}])
    names = [e.name for e in events]

    # Last two events are the error + terminal message_end(max_iterations).
    assert names[-2:] == ["error", "message_end"]
    assert events[-2].data["code"] == "agent.max_iterations"
    assert events[-1].data == {"stop_reason": "max_iterations"}
    # Tool executed once per iteration.
    assert len(registry.executed) == 2


# --------------------------------------------------------------------------- #
# Approval-required tool: Phase-1 stops with tool_rejection, never executes
# --------------------------------------------------------------------------- #


async def test_approval_required_tool_stops_without_executing() -> None:
    turn_1 = [
        _tc(
            index=0,
            call_id="w1",
            name="write_file",
            args_delta='{"path":"a.py","content":"x"}',
            finish="tool_calls",
        ),
    ]
    lm = FakeLM([turn_1])
    registry = FakeRegistry(tools={"write_file": True})  # requires approval
    loop = AgentLoop(lm, registry, _config())  # type: ignore[arg-type]

    events = await _drain(loop, [{"role": "user", "content": "write a file"}])
    names = [e.name for e in events]

    assert names == [
        "message_start",
        "tool_call_start",
        "tool_call_args_delta",
        "tool_call_ready",
        "message_end",
    ]
    ready = events[3].data
    assert ready["requires_approval"] is True
    assert ready["name"] == "write_file"
    assert events[-1].data == {"stop_reason": "tool_rejection"}
    # Never executed and no auto-approval emitted.
    assert registry.executed == []
    assert "tool_call_approved" not in names


# --------------------------------------------------------------------------- #
# Tool raises → tool_call_result status=failed, loop continues
# --------------------------------------------------------------------------- #


async def test_tool_execution_error_yields_failed_result() -> None:
    from skoll.errors import ToolExecutionError

    turn_1 = [
        _tc(
            index=0,
            call_id="c",
            name="codebase_search",
            args_delta='{"query":"x"}',
            finish="tool_calls",
        ),
    ]
    turn_2 = [_text("Sorry, search failed.", finish="stop")]
    lm = FakeLM([turn_1, turn_2])
    registry = FakeRegistry(
        tools={"codebase_search": False},
        errors={"codebase_search": ToolExecutionError("index unavailable")},
    )
    loop = AgentLoop(lm, registry, _config())  # type: ignore[arg-type]

    history: list[dict[str, Any]] = [{"role": "user", "content": "search"}]
    events = await _drain(loop, history)
    by_name = {e.name: e for e in events}

    result = by_name["tool_call_result"].data
    assert result["status"] == "failed"
    assert result["result"] is None
    assert "index unavailable" in result["error"]

    # The failure is fed back to the model as a tool message so it can recover.
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert tool_msgs and '"error"' in tool_msgs[0]["content"]
    # Loop continued to a final answer.
    assert by_name["message_end"].data == {"stop_reason": "end_of_turn"}


# --------------------------------------------------------------------------- #
# Stream failure → error + message_end(error)
# --------------------------------------------------------------------------- #


async def test_stream_failure_emits_error_event() -> None:
    from skoll.errors import LMStudioUnreachableError

    class BrokenLM:
        async def chat_stream(self, **kwargs: Any) -> AsyncIterator[ChatCompletionDelta]:
            raise LMStudioUnreachableError("disconnected")
            yield  # pragma: no cover

    loop = AgentLoop(BrokenLM(), FakeRegistry(tools={}), _config())  # type: ignore[arg-type]
    events = await _drain(loop, [{"role": "user", "content": "hi"}])
    names = [e.name for e in events]
    assert names == ["message_start", "error", "message_end"]
    assert events[1].data["code"] == "lmstudio.unreachable"
    assert events[1].data["recoverable"] is False
    assert events[2].data == {"stop_reason": "error"}
