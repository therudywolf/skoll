"""Reasoning-model detection.

Issue: phase-0.3 (used here for non-streaming chat), phase-1.3 (streaming recovery).

Some local models (qwen3, deepseek-r1, nemotron, o1/o3) emit <think> chains that pollute
tool-call JSON. Detect them and toggle `reasoning: off` on tool-call turns.

Patterns: ported from ForestOptiLM's reasoning_models.py (REASONING_ID_HEURISTIC),
adapted to the simple substring contract documented in the stub.
"""

from __future__ import annotations

import re

# Substring patterns (case-insensitive) that mark a model as a reasoning model.
# Override per-model via config/reasoning_models.yaml.
DEFAULT_REASONING_PATTERNS: tuple[str, ...] = (
    "r1",
    "qwen3",
    "nemotron",
    "o1",
    "o3",
    "o4",
    "deepseek-r",
    "deepthink",
    "magistral",
    "reasoning",
    "thinker",
)

# Greedy, multi-line <think>...</think> matcher. DOTALL so newlines inside the block
# are consumed; IGNORECASE for <Think>/<THINK> variants. Non-greedy per-block so two
# separate think blocks are not merged across intervening real content.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def is_reasoning(model_id: str, extra_patterns: tuple[str, ...] = ()) -> bool:
    """Return True if the model is known to emit a <think> chain.

    Substring match (case-insensitive) against DEFAULT_REASONING_PATTERNS plus any
    caller-supplied extra_patterns (e.g. loaded from config/reasoning_models.yaml).

    Examples:
        is_reasoning("qwen3-coder-32b")    -> True
        is_reasoning("qwen2.5-coder-32b")  -> False
        is_reasoning("deepseek-r1-distill")-> True
    """
    lowered = model_id.lower()
    for pattern in (*DEFAULT_REASONING_PATTERNS, *extra_patterns):
        if pattern and pattern.lower() in lowered:
            return True
    return False


def strip_think_block(text: str) -> str:
    """Remove <think>...</think> blocks from a string (multi-line).

    Used as a last-resort recovery when a reasoning model leaks CoT despite reasoning_off.
    Whitespace left behind by the removed block is stripped from the result edges.
    """
    return _THINK_BLOCK.sub("", text).strip()
