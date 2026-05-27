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

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamingToolCall:
    index: int
    id: str | None = None
    name: str | None = None
    args_buffer: str = ""

    @property
    def is_complete(self) -> bool:
        """True if id, name, and a parseable args JSON are all set."""
        # TODO(phase-1.2)
        raise NotImplementedError

    def try_parse_args(self) -> dict[str, Any] | None:
        """Try to parse args_buffer as JSON. Returns None if not yet valid."""
        # TODO(phase-1.2)
        raise NotImplementedError


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
        """Apply one streaming delta to the accumulator."""
        # TODO(phase-1.2)
        raise NotImplementedError

    def completed(self) -> list[StreamingToolCall]:
        """Return tool calls whose args have fully parsed."""
        # TODO(phase-1.2)
        raise NotImplementedError
