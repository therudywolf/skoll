"""Async LM Studio client.

Issue: phase-0.3.

Wraps both native (/api/v1/*) and OpenAI-compatible (/v1/*) endpoints.
Source of patterns: ForestOptiLM's lm_client.py and lm_studio_api.py — port,
do not directly import (sync vs async).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class LMStudioModel:
    """Subset of fields we care about from /api/v1/models."""

    id: str
    object: str
    loaded_context_length: int | None
    max_context_length: int | None
    capabilities: list[str]  # 'tool_use', 'vision', 'embeddings', etc.


@dataclass(frozen=True)
class ChatCompletionDelta:
    """One chunk of a streaming chat completion."""

    text_delta: str | None
    tool_call_index: int | None
    tool_call_id: str | None
    tool_call_name: str | None
    tool_call_args_delta: str | None
    finish_reason: str | None


class LMStudioClient:
    """Async client for LM Studio.

    Usage:

        async with LMStudioClient.from_settings() as client:
            async for delta in client.chat_stream(messages=..., tools=...):
                ...

    Notes on implementation:
      - Use a single httpx.AsyncClient per instance (connection pooling).
      - Serialize concurrent calls to a single LM Studio instance via asyncio.Semaphore(1)
        — LM Studio is not happy with parallel calls. ForestOptiLM does the same.
      - For reasoning models, set `reasoning: off` (native) or `reasoning_effort: off`
        (openai-compat) on tool-call turns. See skoll.lm.reasoning.is_reasoning.
      - On 4xx, raise LMStudioError with full body; on 5xx and network, retry via tenacity
        with exponential backoff up to N times.
      - NEVER log Authorization header.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_mode: Literal["native", "openai"] = "native",
        timeout_seconds: int = 600,
    ) -> None:
        # TODO(phase-0.3)
        raise NotImplementedError

    @classmethod
    def from_settings(cls) -> LMStudioClient:
        """Build from skoll.config.get_settings()."""
        # TODO(phase-0.3)
        raise NotImplementedError

    async def __aenter__(self) -> LMStudioClient:
        # TODO
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        # TODO
        raise NotImplementedError

    async def list_models(self) -> list[LMStudioModel]:
        """GET /api/v1/models — used to populate /api/health and model selectors."""
        # TODO(phase-0.3)
        raise NotImplementedError

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        reasoning_off: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns the raw model response dict."""
        # TODO(phase-0.4)
        raise NotImplementedError

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        reasoning_off: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[ChatCompletionDelta]:
        """Streaming chat completion. Yields one delta per SSE event from LM Studio.

        Implementation must handle:
          - partial `tool_calls[].function.arguments` chunks (string accumulation)
          - mid-stream disconnects (raise, let caller decide on reconnect)
          - `<think>` block stripping if reasoning_off was requested but model leaked CoT
        """
        # TODO(phase-1.1)
        raise NotImplementedError
        yield  # pragma: no cover  # for type checker

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """POST /v1/embeddings or /api/v1/embeddings."""
        # TODO(phase-1.7)
        raise NotImplementedError
