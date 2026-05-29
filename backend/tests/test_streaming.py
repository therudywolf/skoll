"""Regression tests for the tool-call delta accumulator (Issue 1.2).

These lock in the four edge cases called out in the stub docstring:
  1. Multiple parallel tool calls disambiguated by `index`
  2. Reasoning models leaking a <think> block before the JSON args
  3. Trailing commas in the args JSON (lenient cleanup fallback)
  4. Stream ends mid-args → call is NOT complete and is NOT returned by completed()
"""

from __future__ import annotations

from skoll.agent.streaming import StreamingToolCall, ToolCallAccumulator

# --------------------------------------------------------------------------- #
# StreamingToolCall.try_parse_args / is_complete
# --------------------------------------------------------------------------- #


def test_try_parse_args_valid_json() -> None:
    call = StreamingToolCall(index=0, id="call_1", name="codebase_search")
    call.args_buffer = '{"query": "auth"}'
    assert call.try_parse_args() == {"query": "auth"}
    assert call.is_complete is True


def test_try_parse_args_empty_buffer_is_empty_object() -> None:
    # Zero-arg tools stream "" for arguments — that should parse as {}.
    call = StreamingToolCall(index=0, id="call_1", name="list_things")
    call.args_buffer = ""
    assert call.try_parse_args() == {}
    assert call.is_complete is True


def test_is_complete_false_without_id_or_name() -> None:
    call = StreamingToolCall(index=0, args_buffer='{"query": "x"}')
    assert call.is_complete is False  # no id, no name
    call.id = "call_1"
    assert call.is_complete is False  # still no name
    call.name = "codebase_search"
    assert call.is_complete is True


# --------------------------------------------------------------------------- #
# Edge case 1: parallel tool calls disambiguated by index
# --------------------------------------------------------------------------- #


def test_parallel_tool_calls_kept_separate_by_index() -> None:
    acc = ToolCallAccumulator()
    # Two calls interleave on indices 0 and 1; id/name arrive first, args trickle in.
    acc.absorb_delta(0, "call_a", "codebase_search", None)
    acc.absorb_delta(1, "call_b", "read_file", None)
    acc.absorb_delta(0, None, None, '{"query": ')
    acc.absorb_delta(1, None, None, '{"path": "a.py"')
    acc.absorb_delta(0, None, None, '"login"}')
    acc.absorb_delta(1, None, None, "}")

    completed = acc.completed()
    assert len(completed) == 2
    # Ordered by index.
    assert completed[0].id == "call_a"
    assert completed[0].name == "codebase_search"
    assert completed[0].try_parse_args() == {"query": "login"}
    assert completed[1].id == "call_b"
    assert completed[1].name == "read_file"
    assert completed[1].try_parse_args() == {"path": "a.py"}


def test_id_and_name_not_overwritten_by_later_none() -> None:
    acc = ToolCallAccumulator()
    acc.absorb_delta(0, "call_a", "codebase_search", "")
    acc.absorb_delta(0, None, None, '{"query": "x"}')
    call = acc.calls[0]
    assert call.id == "call_a"
    assert call.name == "codebase_search"


# --------------------------------------------------------------------------- #
# Edge case 2: reasoning model leaks a <think> block before the JSON
# --------------------------------------------------------------------------- #


def test_leaked_think_block_before_args_is_tolerated() -> None:
    acc = ToolCallAccumulator()
    acc.absorb_delta(0, "call_a", "codebase_search", None)
    # Model leaked chain-of-thought before the actual JSON args.
    acc.absorb_delta(0, None, None, "<think>I should search the codebase</think>")
    acc.absorb_delta(0, None, None, '{"query": "auth flow"}')

    completed = acc.completed()
    assert len(completed) == 1
    assert completed[0].try_parse_args() == {"query": "auth flow"}
    assert completed[0].is_complete is True


def test_think_block_multiline_tolerated() -> None:
    call = StreamingToolCall(index=0, id="c", name="codebase_search")
    call.args_buffer = '<think>\nline one\nline two\n</think>\n{"query": "x"}'
    assert call.try_parse_args() == {"query": "x"}


# --------------------------------------------------------------------------- #
# Edge case 3: trailing commas
# --------------------------------------------------------------------------- #


def test_trailing_comma_in_object_is_cleaned() -> None:
    call = StreamingToolCall(index=0, id="c", name="read_file")
    call.args_buffer = '{"path": "a.py", "max_lines": 100,}'
    assert call.try_parse_args() == {"path": "a.py", "max_lines": 100}


def test_trailing_comma_in_nested_array_is_cleaned() -> None:
    call = StreamingToolCall(index=0, id="c", name="codebase_search")
    call.args_buffer = '{"globs": ["*.py", "*.md", ],}'
    assert call.try_parse_args() == {"globs": ["*.py", "*.md"]}


def test_think_block_and_trailing_comma_together() -> None:
    call = StreamingToolCall(index=0, id="c", name="read_file")
    call.args_buffer = '<think>hmm</think>{"path": "x.py",}'
    assert call.try_parse_args() == {"path": "x.py"}


# --------------------------------------------------------------------------- #
# Edge case 4: stream ends mid-args → NOT complete, NOT returned
# --------------------------------------------------------------------------- #


def test_truncated_args_is_not_complete() -> None:
    acc = ToolCallAccumulator()
    acc.absorb_delta(0, "call_a", "codebase_search", None)
    acc.absorb_delta(0, None, None, '{"query": "auth')  # stream died here

    call = acc.calls[0]
    assert call.try_parse_args() is None
    assert call.is_complete is False
    # The half-built call must NOT appear in completed() — we never execute it.
    assert acc.completed() == []


def test_mixed_complete_and_truncated_only_returns_complete() -> None:
    acc = ToolCallAccumulator()
    acc.absorb_delta(0, "call_a", "codebase_search", '{"query": "ok"}')
    acc.absorb_delta(1, "call_b", "read_file", '{"path": ')  # truncated

    completed = acc.completed()
    assert [c.id for c in completed] == ["call_a"]


def test_non_object_args_treated_as_incomplete() -> None:
    # Tool arguments must be a JSON object; a bare array/scalar is not usable.
    call = StreamingToolCall(index=0, id="c", name="x")
    call.args_buffer = "[1, 2, 3]"
    assert call.try_parse_args() is None
    assert call.is_complete is False
