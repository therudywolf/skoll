# TESTED_MODELS.md — LM Studio model compatibility matrix

> **Owner pre-populates this file from ForestOptiLM experience and updates it as Phase 1/2 tests catch new quirks.**
> Each new model that's tested in a PR must add a row.

## Format

| Model | Quant | Tool calling | Streaming tool args | Reasoning toggle needed | Vision | Notes |
|---|---|---|---|---|---|---|

## Confirmed working (May 2026)

| Model | Quant | Tool calling | Streaming tool args | Reasoning toggle needed | Vision | Notes |
|---|---|---|---|---|---|---|
| qwen2.5-coder-32b-instruct | Q4_K_M | ✅ | ✅ | no | ❌ | Best price/perf for coding tasks. |
| qwen3-coder-32b | Q4_K_M | ✅ | ⚠️ partial | **yes** — `reasoning: off` | ❌ | Without `reasoning: off`, the model mixes `<think>` blocks into tool args, breaking JSON. |
| deepseek-coder-v2-lite-16b | Q5_K_M | ✅ | ✅ | no | ❌ | Fast on consumer GPUs. |
| deepseek-r1-distill-qwen-32b | Q4_K_M | ⚠️ | ❌ | **yes** — `reasoning: off` | ❌ | Tool calls work non-streaming only. Use for analysis tasks, not interactive agent. |
| llama-3.3-70b-instruct | Q3_K_M | ✅ | ✅ | no | ❌ | Heavy; only on 48GB+ VRAM. |
| nemotron-nano-v2-12b | Q5_K_M | ✅ | ✅ | no | ❌ | Added LM Studio 0.3.x. Solid all-rounder. |
| qwen2.5-vl-7b-instruct | Q5_K_M | ✅ | ✅ | no | ✅ | Vision + tool calls. Use for `analyze_image`. |
| nomic-embed-text-v1.5 | F16 | n/a | n/a | n/a | n/a | Embedding model. Set as embeddings backend in LM Studio. |

## Known broken / quirky

| Model | Issue |
|---|---|
| `*-r1-*` (any reasoning variant) without `reasoning: off` | `<think>` tokens pollute tool call JSON, makes args unparseable. Always set `reasoning: off` for tool-call requests. |
| Old (pre-0.3.6) LM Studio versions | Tool name normalization not applied → camelCase names fail silently |
| Models with `<5B` parameters | Generally unreliable at tool calling; agent loops fail with malformed args >40% of the time |
| `phi-3.5-mini` | Tool calling support claimed but JSON output is inconsistent; not recommended |

## Recommended profiles (`config/run_profiles.yaml`)

These mirror the ForestOptiLM pattern (different model per agent role):

| Role | Suggested model | Why |
|---|---|---|
| `agent_default` | qwen2.5-coder-32b-instruct | Best balance for read+write+exec tools |
| `agent_planner` | deepseek-r1-distill-qwen-32b (with reasoning) | For initial planning step, then hand off to default |
| `vision` | qwen2.5-vl-7b-instruct | Image analysis |
| `embedding` | nomic-embed-text-v1.5 | RAG embeddings |
| `quick_classify` | qwen2.5-coder-7b-instruct Q4 | Fast classification (e.g., "is this file relevant?") in scout phases |

## How to add a model to this matrix

1. Load the model in LM Studio with tool calling enabled.
2. Run `backend/scripts/probe_model.py --model <id>`. This runs the standard probe: simple chat, chat with tool definition, streaming + tool call, malformed-recovery scenario.
3. Add the row with the captured results.
4. Commit the probe output to `examples/model_probes/<id>.json` for future regression.
