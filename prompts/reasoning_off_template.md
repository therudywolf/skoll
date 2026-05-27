# Reasoning toggle for LM Studio requests

> When calling tool-aware models that internally emit `<think>` chains (qwen3, deepseek-r1, nemotron, etc.), the chain pollutes tool call JSON.
> This file documents how to suppress it.

## The flag

LM Studio native API (`/api/v1/chat`):

```json
{
  "model": "qwen3-coder-32b",
  "messages": [...],
  "tools": [...],
  "reasoning": "off"
}
```

LM Studio OpenAI-compat API (`/v1/chat/completions`):

```json
{
  "model": "qwen3-coder-32b",
  "messages": [...],
  "tools": [...],
  "reasoning_effort": "off"
}
```

(Some models support `low | medium | high | off`; treat unsupported values as fallback to default.)

## When to apply

| Scenario | Reasoning |
|---|---|
| Tool-call iteration in agent loop | **off** — required for stable JSON |
| Final assistant message (no tools expected) | leave default (model's normal behavior) |
| Initial planning step (user asks "plan this refactor") | **on (medium)** if model supports it — better plans |
| Embeddings request | n/a |

## Detection

`skoll.lm.reasoning.is_reasoning(model_id: str) -> bool`:

Returns True if the model id matches any of (case-insensitive substring match):
- `r1`
- `qwen3`
- `nemotron`
- `o1`, `o3`, `o4`
- explicit override in `config/reasoning_models.yaml`

When True, the LM client automatically sets `reasoning: off` for tool-call turns.

## What if you forget

Symptoms:
- `tool_calls[*].function.arguments` arrives as `"<think>\nUser wants me to ...\n</think>\n{\"path\": ..."` — extra text breaks JSON parse.
- `text_delta` events leak the chain into the UI as visible noise.

Both are surfaced as `invalid_arguments` recovery errors but cause user-visible flicker. Avoid by always calling `is_reasoning()` first.
