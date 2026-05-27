# Tool-call recovery prompt

> Used when the LLM emits a malformed `tool_calls.function.arguments` (e.g. invalid JSON, missing required field, type mismatch).
> The backend constructs a synthetic tool result and appends it to history; on the next iteration the agent sees this and retries.

## Synthetic message format

When parsing fails, backend appends:

```
{
  "role": "tool",
  "tool_call_id": "<the failed tool_call_id>",
  "content": "<error JSON, see below>"
}
```

Error content schema:

```json
{
  "error": "invalid_arguments",
  "tool": "write_file",
  "details": "JSON parse failed at column 47: unexpected token",
  "raw_arguments": "<the broken JSON string>",
  "recovery_hint": "Emit only valid JSON. No leading text, no <think> blocks, no trailing commas."
}
```

## Why this matters for reasoning models

Models like qwen3, deepseek-r1, nemotron may include `<think>...</think>` blocks before or inside their tool-call arguments. Always set `reasoning: off` in the chat request for tool-call turns to suppress these. If they leak anyway:

1. Backend parser strips `<think>...</think>` if present and retries JSON parse.
2. If parse still fails, emit the synthetic error above.
3. After 3 consecutive recovery attempts on the same tool call, abort the iteration and surface the error to the user.

## Anti-loop protection

- Max recovery iterations per turn: 3
- After 3 fails, the agent loop sets `stop_reason: "error"` and emits an `error` SSE event.
- The user sees: *"The model couldn't produce valid arguments for `write_file` after 3 attempts. The raw output is in the dev console."*

## Recovery hint variations (per error type)

| Error | `recovery_hint` |
|---|---|
| `invalid_json` | "Emit only valid JSON. No leading text, no `<think>` blocks, no trailing commas." |
| `missing_required` | "The field `<name>` is required. See the tool's parameter schema." |
| `type_mismatch` | "Field `<name>` must be a `<type>`, got `<actual>`." |
| `enum_violation` | "Field `<name>` must be one of: `<allowed values>`." |
| `path_outside_workspace` | "Paths must be relative to the workspace root and may not escape it." |
| `search_not_found` (apply_diff) | "The `search` text was not found in the file. Re-read the file and use the exact current text." |
