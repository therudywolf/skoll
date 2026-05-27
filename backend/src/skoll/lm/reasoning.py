"""Reasoning-model detection.

Issue: phase-1.3.

Some local models (qwen3, deepseek-r1, nemotron, o1/o3) emit <think> chains that pollute
tool-call JSON. Detect them and toggle `reasoning: off` on tool-call turns.

Patterns: see ForestOptiLM's reasoning_models.py for the canonical list.
"""

from __future__ import annotations

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
)


def is_reasoning(model_id: str, extra_patterns: tuple[str, ...] = ()) -> bool:
    """Return True if the model is known to emit a <think> chain.

    Implementation:
      - lowercase the model id
      - return True if any pattern is a substring
      - also load overrides from config/reasoning_models.yaml at startup (caller's job)
    """
    # TODO(phase-1.3)
    raise NotImplementedError


def strip_think_block(text: str) -> str:
    """Remove <think>...</think> blocks from a string (greedy, multi-line).

    Used as a last-resort recovery when a reasoning model leaks CoT despite reasoning_off.
    """
    # TODO(phase-1.3)
    raise NotImplementedError
