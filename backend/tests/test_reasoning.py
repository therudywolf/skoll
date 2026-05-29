"""Tests for reasoning-model detection (Issues 0.3 + 1.3).

Covers the stable name heuristic (``is_reasoning`` / ``strip_think_block``) and the
metadata-aware refinement (``model_uses_reasoning``). No LM Studio, no network — we build
``LMStudioModel`` instances directly.
"""

from __future__ import annotations

import pytest
from skoll.lm.client import LMStudioModel
from skoll.lm.reasoning import is_reasoning, model_uses_reasoning, strip_think_block


def _model(model_id: str, capabilities: list[str]) -> LMStudioModel:
    return LMStudioModel(
        id=model_id,
        object="model",
        loaded_context_length=8192,
        max_context_length=32768,
        capabilities=capabilities,
    )


# --------------------------------------------------------------------------- #
# is_reasoning — name heuristic (stable contract)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("qwen3-coder-32b", True),
        ("qwen3-coder-30b-a3b-instruct", True),
        ("deepseek-r1-distill-qwen-7b", True),
        ("nvidia-nemotron-49b", True),
        ("o3-mini", True),
        ("magistral-small", True),
        ("qwen2.5-coder-32b", False),
        ("qwen2.5-coder-32b-instruct", False),
        ("llama-3.1-8b-instruct", False),
        ("gemma-2-9b-it", False),
        ("nomic-embed-text-v1.5", False),
    ],
)
def test_is_reasoning_name_cases(model_id: str, expected: bool) -> None:
    assert is_reasoning(model_id) is expected


def test_is_reasoning_extra_patterns() -> None:
    # Caller-supplied patterns (e.g. from config/reasoning_models.yaml) extend the defaults.
    assert is_reasoning("mycorp-think-v2", extra_patterns=("mycorp-think",)) is True
    assert is_reasoning("mycorp-plain-v2", extra_patterns=("mycorp-think",)) is False


# --------------------------------------------------------------------------- #
# model_uses_reasoning — metadata + name fallback (Issue 1.3)
# --------------------------------------------------------------------------- #


def test_model_uses_reasoning_true_from_capability() -> None:
    # A name that the heuristic would NOT flag, but metadata says reasoning -> True.
    model = _model("acme-coder-7b", capabilities=["reasoning", "tool_use"])
    assert model_uses_reasoning(model) is True


def test_model_uses_reasoning_true_from_thinking_capability() -> None:
    model = _model("acme-coder-7b", capabilities=["thinking"])
    assert model_uses_reasoning(model) is True


def test_model_uses_reasoning_capability_case_insensitive() -> None:
    model = _model("acme-coder-7b", capabilities=["Reasoning"])
    assert model_uses_reasoning(model) is True


def test_model_uses_reasoning_false_when_only_tool_use() -> None:
    model = _model("qwen2.5-coder-32b-instruct", capabilities=["tool_use"])
    assert model_uses_reasoning(model) is False


def test_model_uses_reasoning_false_when_no_capabilities_and_plain_name() -> None:
    model = _model("llama-3.1-8b-instruct", capabilities=[])
    assert model_uses_reasoning(model) is False


def test_model_uses_reasoning_name_fallback_when_capabilities_empty() -> None:
    # Metadata omits the capability, but the id matches the heuristic -> still True.
    model = _model("qwen3-coder-30b-a3b-instruct", capabilities=[])
    assert model_uses_reasoning(model) is True


def test_model_uses_reasoning_name_flags_even_with_tool_use() -> None:
    # A known reasoning model that also advertises tool_use is still a reasoning model.
    model = _model("deepseek-r1-distill-qwen-7b", capabilities=["tool_use"])
    assert model_uses_reasoning(model) is True


def test_model_uses_reasoning_respects_extra_patterns() -> None:
    model = _model("mycorp-think-v2", capabilities=[])
    assert model_uses_reasoning(model, extra_patterns=("mycorp-think",)) is True


# --------------------------------------------------------------------------- #
# strip_think_block
# --------------------------------------------------------------------------- #


def test_strip_think_block_removes_block() -> None:
    text = "<think>secret chain of thought\nmore lines</think>Here is the answer."
    assert strip_think_block(text) == "Here is the answer."


def test_strip_think_block_no_block_is_noop() -> None:
    assert strip_think_block("just text") == "just text"


def test_strip_think_block_case_insensitive_and_multiblock() -> None:
    text = "<Think>a</Think>keep1<THINK>b\nc</THINK>keep2"
    assert strip_think_block(text) == "keep1keep2"
