# LM Studio fixtures

Captured request/response pairs from a real LM Studio instance. Used to make tests
deterministic without requiring LM Studio to be running.

## How to capture a new fixture

```bash
cd backend
uv run python -m skoll.lm.capture \
    --base-url http://127.0.0.1:1234 \
    --model qwen2.5-coder-32b-instruct \
    --scenario streaming_tool_call \
    > tests/fixtures/lm_studio/qwen25_streaming_tool_call.txt
```

The capture tool (TODO: phase-0.3) records the raw SSE bytes for a single chat call.

## Required fixtures (must exist before phase-1 tests pass)

- `chat_simple_nontool.json` — one-shot non-streaming response, no tools
- `chat_streaming_text.txt` — streaming text, no tools
- `chat_streaming_tool_call.txt` — streaming with one tool call (well-formed)
- `chat_streaming_tool_call_partial.txt` — same but stream cuts off mid-args
- `chat_reasoning_leak.txt` — qwen3-style `<think>` block leaked into args
- `chat_malformed_json.txt` — bad trailing comma in tool args
- `error_400_invalid_model.json` — error response shape
- `models_list.json` — `/api/v1/models` response with mixed capabilities
