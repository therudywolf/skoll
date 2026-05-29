"""Tool-call delta accumulator.

Issue: phase-1.2.

LM Studio streams tool calls as: `function.arguments` arrives as a growing string
across multiple deltas. We must buffer until the JSON is valid, then parse.

Edge cases this MUST handle (regression tests live in tests/test_streaming.py):
  1. Multiple parallel tool calls — `index` distinguishes them
  2. Reasoning models leaking <think> blocks before the JSON
  3. Trailing commas (some models emit them — be lenient with json5 fallback)
  4. Stream ends mid-args → emit error, do NOT call the tool
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from skoll.lm.reasoning import strip_think_block

# Matches a trailing comma directly before a closing brace/bracket, e.g. ``{"a": 1,}``
# or ``[1, 2, ]``. Applied as a cleanup fallback when strict json.loads fails — some
# local models emit them. Whitespace (incl. newlines) between the comma and the closer
# is tolerated.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _lenient_json_object(buffer: str) -> dict[str, Any] | None:
    """Parse ``buffer`` into a JSON object, tolerating reasoning leakage / trailing commas.

    Strategy, cheapest first:
      1. Strict ``json.loads`` on the raw buffer.
      2. Strip any leaked ``<think>...</think>`` block (reasoning models sometimes emit
         their chain-of-thought before the JSON despite ``reasoning: off``), then retry.
      3. Slice to the outermost ``{ ... }`` span and drop trailing commas, then retry.

    Returns the parsed ``dict`` on success, or ``None`` if the buffer is not (yet) a valid
    JSON object. Only objects are accepted — tool arguments are always a JSON object, so a
    bare array/scalar is treated as not-yet-valid rather than a usable parse.
    """
    if not buffer.strip():
        return None

    # 1. Fast path: already-valid JSON.
    parsed = _try_loads_object(buffer)
    if parsed is not None:
        return parsed

    # 2. Drop a leaked <think>...</think> block, then retry the fast path.
    stripped = strip_think_block(buffer)
    if stripped != buffer:
        parsed = _try_loads_object(stripped)
        if parsed is not None:
            return parsed
    else:
        stripped = buffer

    # 3. Slice to the outermost object span and remove trailing commas.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = stripped[start : end + 1]
    candidate = _TRAILING_COMMA.sub(r"\1", candidate)
    return _try_loads_object(candidate)


def _try_loads_object(text: str) -> dict[str, Any] | None:
    """``json.loads`` ``text`` and return it only if it is a dict, else ``None``."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(value, dict):
        return value
    return None


@dataclass
class StreamingToolCall:
    index: int
    id: str | None = None
    name: str | None = None
    args_buffer: str = ""

    @property
    def is_complete(self) -> bool:
        """True if id, name, and a parseable args JSON are all set."""
        return self.id is not None and self.name is not None and self.try_parse_args() is not None

    def try_parse_args(self) -> dict[str, Any] | None:
        """Try to parse args_buffer as JSON. Returns None if not yet valid.

        Lenient: tolerates a leading ``<think>...</think>`` block and trailing commas
        (see ``_lenient_json_object``). An empty buffer is treated as an empty-argument
        call (``{}``) so zero-arg tools (LM Studio often streams ``""`` for these) are
        considered parseable rather than stuck forever.
        """
        if not self.args_buffer.strip():
            return {}
        return _lenient_json_object(self.args_buffer)


@dataclass
class ToolCallAccumulator:
    """Maintains state for in-flight tool calls during a single LM Studio stream."""

    calls: dict[int, StreamingToolCall] = field(default_factory=dict)

    def absorb_delta(
        self,
        index: int,
        call_id: str | None,
        name: str | None,
        args_delta: str | None,
    ) -> None:
        """Apply one streaming delta to the accumulator.

        ``index`` is the stable per-call slot LM Studio uses to disambiguate parallel
        tool calls; deltas for the same call share an index even when ``id``/``name``
        arrive only in the first chunk and ``args_delta`` trickles in afterwards. ``id``
        and ``name``, once seen, are never overwritten by a later ``None``; ``args_delta``
        is appended in arrival order.
        """
        call = self.calls.get(index)
        if call is None:
            call = StreamingToolCall(index=index)
            self.calls[index] = call

        if call_id is not None:
            call.id = call_id
        if name is not None:
            call.name = name
        if args_delta:
            call.args_buffer += args_delta

    def completed(self) -> list[StreamingToolCall]:
        """Return tool calls whose args have fully parsed, ordered by index.

        A call is returned only when it ``is_complete`` (id + name + parseable args). A
        call whose argument buffer never became valid JSON — e.g. the stream ended
        mid-args — is intentionally omitted so the caller never executes a half-built
        tool call.
        """
        return [self.calls[index] for index in sorted(self.calls) if self.calls[index].is_complete]
