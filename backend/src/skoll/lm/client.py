"""Async LM Studio client.

Issue: phase-0.3.

Wraps both native (/api/v1/*) and OpenAI-compatible (/v1/*) endpoints.
Source of patterns: ForestOptiLM's lm_client.py and lm_studio_api.py — port,
do not directly import (sync vs async).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from skoll.errors import LMStudioAuthError, LMStudioError, LMStudioUnreachableError
from skoll.lm.reasoning import is_reasoning, strip_think_block

if TYPE_CHECKING:
    from types import TracebackType

logger = structlog.get_logger(__name__)

# Native REST v1 (LM Studio 0.4+).
_NATIVE_MODELS = "/api/v1/models"
_NATIVE_CHAT = "/api/v1/chat"
_NATIVE_EMBEDDINGS = "/api/v1/embeddings"

# OpenAI-compatible (same server).
_OPENAI_MODELS = "/v1/models"
_OPENAI_CHAT = "/v1/chat/completions"
_OPENAI_EMBEDDINGS = "/v1/embeddings"

# Retry tuning for transient failures (5xx / network). 4xx is never retried.
_RETRY_ATTEMPTS = 3
_RETRY_WAIT_MIN = 0.5
_RETRY_WAIT_MAX = 8.0


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


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers safe to log — the bearer token is never exposed.

    Matches the Authorization header case-insensitively (httpx lowercases header keys,
    so a naive ``"Authorization" in headers`` check would miss the real ``authorization``
    key and leak the token).
    """
    redacted = dict(headers)
    for key in list(redacted):
        if key.lower() == "authorization":
            redacted[key] = "Bearer [REDACTED]"
    return redacted


def _coerce_capabilities(raw: object) -> list[str]:
    """Normalise the many shapes LM Studio uses for `capabilities`.

    Newer native builds emit a list (``["tool_use", "vision"]``); some emit a dict of
    feature -> bool/spec (``{"tool_use": true, "reasoning": {...}}``). We reduce both to
    a sorted list of enabled capability names so callers have one stable shape.
    """
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, str)]
    if isinstance(raw, dict):
        names: list[str] = []
        for key, value in raw.items():
            # A capability is "present" if its value is truthy (True, or a spec object).
            if value is False or value is None:
                continue
            names.append(str(key))
        return sorted(names)
    return []


def _to_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly.
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        iv = int(value.strip())
        return iv if iv > 0 else None
    return None


def _parse_model_item(item: dict[str, Any]) -> LMStudioModel | None:
    """Parse one entry from either a native or an openai-compat /models payload."""
    mid = item.get("id") or item.get("key")
    if not mid:
        return None
    return LMStudioModel(
        id=str(mid),
        object=str(item.get("object") or "model"),
        loaded_context_length=_to_int_or_none(item.get("loaded_context_length")),
        max_context_length=_to_int_or_none(
            item.get("max_context_length") or item.get("context_length")
        ),
        capabilities=_coerce_capabilities(item.get("capabilities")),
    )


# Sentinel object returned by `_parse_sse_line` for the terminal `data: [DONE]` line.
# A distinct object (not None) so it is unambiguous against "ignore this line" (None).
_DONE_SENTINEL = ChatCompletionDelta(
    text_delta=None,
    tool_call_index=None,
    tool_call_id=None,
    tool_call_name=None,
    tool_call_args_delta=None,
    finish_reason=None,
)


def _parse_sse_line(line: str) -> ChatCompletionDelta | None:
    """Parse one raw SSE line from an LM Studio stream into a delta.

    Returns:
      - ``_DONE_SENTINEL`` for the terminal ``data: [DONE]`` line,
      - a :class:`ChatCompletionDelta` for a parseable ``data: {json}`` chunk,
      - ``None`` for blank lines, comments (``:`` keep-alives), non-``data:`` fields,
        or a ``data:`` whose JSON is unusable — the caller skips these.

    Only the first choice is read. Both the openai-compat shape
    (``choices[0].delta.{content,tool_calls}``) and native variants that nest the same
    fields under ``message`` are handled.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        # Blank separator line or an SSE comment / keep-alive.
        return None
    if not stripped.startswith("data:"):
        # `event:` / `id:` / `retry:` fields carry no completion payload for us.
        return None

    data = stripped[len("data:") :].strip()
    if data == "[DONE]":
        return _DONE_SENTINEL
    try:
        chunk = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(chunk, dict):
        return None

    return _delta_from_chunk(chunk)


def _delta_from_chunk(chunk: dict[str, Any]) -> ChatCompletionDelta | None:
    """Extract a :class:`ChatCompletionDelta` from one parsed streaming chunk.

    Returns ``None`` if the chunk carries no choices. A chunk with a choice but no
    incremental payload (e.g. a lone ``finish_reason``) still yields a delta so the caller
    learns the turn ended.
    """
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None

    finish_reason = first.get("finish_reason")
    finish_str = finish_reason if isinstance(finish_reason, str) else None

    # openai-compat uses `delta`; some native builds use `message` for the same fields.
    payload = first.get("delta")
    if not isinstance(payload, dict):
        payload = first.get("message")
    if not isinstance(payload, dict):
        payload = {}

    text = payload.get("content")
    text_delta = text if isinstance(text, str) and text != "" else None

    (
        tc_index,
        tc_id,
        tc_name,
        tc_args,
    ) = _extract_tool_call_fragment(payload.get("tool_calls"))

    return ChatCompletionDelta(
        text_delta=text_delta,
        tool_call_index=tc_index,
        tool_call_id=tc_id,
        tool_call_name=tc_name,
        tool_call_args_delta=tc_args,
        finish_reason=finish_str,
    )


def _extract_tool_call_fragment(
    tool_calls: object,
) -> tuple[int | None, str | None, str | None, str | None]:
    """Pull the (index, id, name, args_delta) fragment from a streaming ``tool_calls``.

    LM Studio streams at most one tool-call fragment per chunk (the openai-compat
    convention); we read the first element. ``index`` defaults to 0 when absent so a
    single-tool stream that omits it still lands in a stable slot.
    """
    if not isinstance(tool_calls, list) or not tool_calls:
        return (None, None, None, None)
    entry = tool_calls[0]
    if not isinstance(entry, dict):
        return (None, None, None, None)

    raw_index = entry.get("index")
    index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else 0

    call_id_raw = entry.get("id")
    call_id = call_id_raw if isinstance(call_id_raw, str) and call_id_raw else None

    name: str | None = None
    args_delta: str | None = None
    function = entry.get("function")
    if isinstance(function, dict):
        fn_name = function.get("name")
        if isinstance(fn_name, str) and fn_name:
            name = fn_name
        fn_args = function.get("arguments")
        if isinstance(fn_args, str) and fn_args != "":
            args_delta = fn_args

    return (index, call_id, name, args_delta)


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
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_mode: Literal["native", "openai"] = api_mode
        self.timeout_seconds = timeout_seconds
        # One client per instance for connection pooling.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(float(timeout_seconds)),
            headers=self._auth_headers(),
        )
        # LM Studio dislikes parallel calls to a single instance — serialize them.
        self._semaphore = asyncio.Semaphore(1)

    @classmethod
    def from_settings(cls) -> LMStudioClient:
        """Build from skoll.config.get_settings()."""
        from skoll.config import get_settings

        s = get_settings().lmstudio
        return cls(
            base_url=s.base_url,
            api_key=s.api_key,
            api_mode=s.api_mode,
            timeout_seconds=s.timeout_seconds,
        )

    async def __aenter__(self) -> LMStudioClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.aclose()

    # ----- internal helpers -------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    @property
    def _models_path(self) -> str:
        return _NATIVE_MODELS if self.api_mode == "native" else _OPENAI_MODELS

    @property
    def _chat_path(self) -> str:
        return _NATIVE_CHAT if self.api_mode == "native" else _OPENAI_CHAT

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Translate a 4xx into the right skoll.errors.* exception.

        The full response body is attached to the error (it is LM Studio's, not the
        user's content), but the Authorization header is NEVER logged or embedded.
        """
        status = response.status_code
        if status < 400:
            return
        body = response.text
        if status in (401, 403):
            logger.warning(
                "lmstudio.auth_error",
                status_code=status,
                request_headers=_redact_headers(dict(response.request.headers)),
            )
            raise LMStudioAuthError(f"LM Studio auth failed (HTTP {status}): {body}")
        # Other 4xx (e.g. 400 bad model / bad payload). Do not retry.
        logger.warning(
            "lmstudio.client_error",
            status_code=status,
            request_headers=_redact_headers(dict(response.request.headers)),
        )
        raise LMStudioError(f"LM Studio request failed (HTTP {status}): {body}")

    @retry(
        retry=retry_if_exception_type(LMStudioUnreachableError),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
        reraise=True,
    )
    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue one request and return parsed JSON.

        Transient failures (network errors, 5xx) are normalised to
        LMStudioUnreachableError and retried with exponential backoff. 4xx raises a
        non-retried LMStudioError via `_raise_for_status`. The ONLY exception types that
        escape this method are skoll.errors.LMStudioError and its subclasses — callers
        never have to handle a raw httpx exception.
        """
        try:
            response = await self._client.request(method, path, json=json_body)
        except httpx.TransportError as exc:
            # Network-level failure: connection refused, DNS, read timeout, etc.
            logger.warning("lmstudio.transport_error", path=path, error=str(exc))
            raise LMStudioUnreachableError(
                f"LM Studio is unreachable at {self.base_url}: {exc!s}"
            ) from exc
        if response.status_code >= 500:
            logger.warning("lmstudio.server_error", path=path, status_code=response.status_code)
            # Wrap 5xx so tenacity retries it (it is transient on the server side).
            raise LMStudioUnreachableError(f"LM Studio server error (HTTP {response.status_code})")
        self._raise_for_status(response)
        data = response.json()
        if not isinstance(data, dict):
            raise LMStudioError("LM Studio returned a non-object JSON response")
        return cast("dict[str, Any]", data)

    # ----- public API -------------------------------------------------------

    async def list_models(self) -> list[LMStudioModel]:
        """GET /api/v1/models — used to populate /api/health and model selectors.

        Parses both the native shape (``{"data": [...]}`` with native fields) and the
        openai-compat shape (``{"object": "list", "data": [...]}``).
        """
        async with self._semaphore:
            data = await self._request_json("GET", self._models_path)
        raw_items = data.get("data")
        if not isinstance(raw_items, list):
            # Some builds key the array as "models".
            raw_items = data.get("models")
        models: list[LMStudioModel] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    parsed = _parse_model_item(item)
                    if parsed is not None:
                        models.append(parsed)
        return models

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        reasoning_off: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns the raw model response dict.

        `reasoning_off` (or an auto-detected reasoning model) toggles the
        endpoint-appropriate reasoning switch so `<think>` chains do not pollute the
        response / tool-call JSON.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        # A reasoning model on a tool-call turn (or an explicit caller request) gets the
        # reasoning channel turned off. Native uses `reasoning`, openai-compat uses
        # `reasoning_effort` (LM Studio accepts both depending on build/endpoint).
        if reasoning_off or is_reasoning(model):
            if self.api_mode == "native":
                payload["reasoning"] = "off"
            else:
                payload["reasoning_effort"] = "off"
        # Caller passthrough (temperature, max_tokens, etc.). Never overrides stream.
        for key, value in kwargs.items():
            if key != "stream":
                payload[key] = value

        async with self._semaphore:
            data = await self._request_json("POST", self._chat_path, json_body=payload)
        return data

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        reasoning_off: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[ChatCompletionDelta]:
        """Streaming chat completion. Yields one delta per SSE event from LM Studio.

        Opens an SSE stream against the native (``/api/v1/chat``) or openai-compat
        (``/v1/chat/completions``) endpoint with ``"stream": true``, parses each
        ``data:`` line into a :class:`ChatCompletionDelta`, and yields it. The terminal
        ``data: [DONE]`` sentinel ends the stream cleanly.

        Implementation notes:
          - partial ``tool_calls[].function.arguments`` arrive as a growing string across
            chunks; we surface each fragment as ``tool_call_args_delta`` and let the caller
            (ToolCallAccumulator) buffer until the JSON parses — we never parse here.
          - the per-call ``index`` disambiguates parallel tool calls.
          - mid-stream disconnect (the transport drops before ``[DONE]`` / a finish_reason)
            raises ``LMStudioUnreachableError`` so the caller can decide on reconnect.
          - reasoning models (or an explicit ``reasoning_off``) get the endpoint-appropriate
            reasoning switch so a ``<think>`` chain never pollutes the tool-call JSON.
          - concurrency to a single LM Studio instance stays at 1 via the Semaphore, held for
            the whole stream.

        This method is NOT wrapped by the tenacity retry on ``_request_json`` — a partially
        consumed stream cannot be safely replayed, so reconnect is the caller's decision.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if reasoning_off or is_reasoning(model):
            if self.api_mode == "native":
                payload["reasoning"] = "off"
            else:
                payload["reasoning_effort"] = "off"
        for key, value in kwargs.items():
            if key != "stream":
                payload[key] = value

        # The Semaphore is held for the entire stream — LM Studio serializes one
        # generation at a time per instance (AGENTS.md §7.6).
        async with self._semaphore:
            try:
                async with self._client.stream("POST", self._chat_path, json=payload) as response:
                    if response.status_code >= 400:
                        # Buffer the body so `.text` (used by `_raise_for_status`) is
                        # populated — httpx caches the read content on the response.
                        await response.aread()
                        if response.status_code >= 500:
                            logger.warning(
                                "lmstudio.stream_server_error",
                                path=self._chat_path,
                                status_code=response.status_code,
                            )
                            raise LMStudioUnreachableError(
                                f"LM Studio server error (HTTP {response.status_code})"
                            )
                        self._raise_for_status(response)

                    saw_terminal = False
                    async for line in response.aiter_lines():
                        delta = _parse_sse_line(line)
                        if delta is _DONE_SENTINEL:
                            saw_terminal = True
                            break
                        if delta is None:
                            continue
                        if delta.finish_reason is not None:
                            saw_terminal = True
                        yield delta
            except httpx.TransportError as exc:
                # Connection dropped mid-stream (or could not be established). The caller
                # decides whether to reconnect; we do not silently swallow partial output.
                logger.warning(
                    "lmstudio.stream_transport_error", path=self._chat_path, error=str(exc)
                )
                raise LMStudioUnreachableError(f"LM Studio stream disconnected: {exc!s}") from exc

        if not saw_terminal:
            # Stream closed without [DONE] or a finish_reason — treat as a mid-stream
            # disconnect so the caller does not mistake a truncated turn for a clean one.
            raise LMStudioUnreachableError(
                "LM Studio stream ended before completion (no finish_reason / [DONE])"
            )

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Return one embedding vector per input text.

        POSTs to the native (``/api/v1/embeddings``) or openai-compat
        (``/v1/embeddings``) endpoint depending on ``api_mode``. Both shapes return
        ``{"data": [{"embedding": [...]}, ...]}`` so a single parser handles them.

        Inputs are sent in batches (LM Studio embedding servers cap request size);
        each batch goes through :meth:`_request_json`, so transient 5xx / network
        failures are retried and 4xx raises a non-retried ``LMStudioError`` — the
        same error contract as :meth:`chat`. The Semaphore keeps concurrency at 1.
        """
        if not texts:
            return []

        # LM Studio embedding servers reject very large request bodies; batch them.
        batch_size = 32
        path = _NATIVE_EMBEDDINGS if self.api_mode == "native" else _OPENAI_EMBEDDINGS

        vectors: list[list[float]] = []
        async with self._semaphore:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                payload: dict[str, Any] = {"model": model, "input": batch}
                data = await self._request_json("POST", path, json_body=payload)
                # Native and openai-compat both return {"data": [{"embedding": [...]}]}.
                items = data.get("data")
                if not isinstance(items, list):
                    raise LMStudioError("LM Studio embeddings response missing a 'data' array")
                batch_vectors: list[list[float]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    emb = item.get("embedding")
                    if isinstance(emb, list):
                        batch_vectors.append([float(v) for v in emb])
                if len(batch_vectors) != len(batch):
                    raise LMStudioError(
                        f"Embedding batch size mismatch: expected {len(batch)} vectors, "
                        f"got {len(batch_vectors)}"
                    )
                vectors.extend(batch_vectors)

        if len(vectors) != len(texts):
            raise LMStudioError(
                f"Embedding response size mismatch: expected {len(texts)} vectors, "
                f"got {len(vectors)}. Is an embeddings-capable model loaded in LM Studio?"
            )
        return vectors


def extract_assistant_content(response: dict[str, Any]) -> str:
    """Pull the assistant text out of a non-streaming chat response.

    Handles the OpenAI-compatible ``choices[0].message.content`` shape and the native
    LM Studio variants. If a reasoning model leaked a ``<think>`` block into the content
    despite ``reasoning: off``, it is stripped. Ported from ForestOptiLM's
    ``extract_chat_response_content`` (content half only).
    """
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return strip_think_block(content)

    # Native top-level "content".
    top = response.get("content")
    if isinstance(top, str) and top.strip():
        return strip_think_block(top)

    # Native "output" list (message / text parts).
    output = response.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").strip().lower()
            if typ in ("message", "text", "output_text"):
                piece = item.get("content") or item.get("text")
                if isinstance(piece, str) and piece:
                    parts.append(piece)
        if parts:
            return strip_think_block("\n".join(parts))

    return ""
