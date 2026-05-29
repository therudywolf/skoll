"""Tests for the codebase_search tool (Issue 1.9).

No LM Studio, no network: ``embed_chunks`` is monkeypatched and the WorkspaceIndex is a
real in-memory FAISS index seeded with fake vectors. The result shape is asserted against
contracts/tools/codebase_search.json's result_schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import skoll.config as config_mod
from skoll.agent.tools import codebase_search
from skoll.agent.tools.registry import ToolContext
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.rag.retrieval import Chunk, WorkspaceIndex

# 3-dim fake embedding space; query vectors are hand-picked to select a known chunk.
_DIM = 3
_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "tools" / "codebase_search.json"


@pytest.fixture(autouse=True)
def _reset_settings_singleton() -> Any:
    config_mod._settings = None
    yield
    config_mod._settings = None


@pytest.fixture(autouse=True)
def _reset_index_provider() -> Any:
    """Restore the default provider after each test (it's module-global)."""
    original = codebase_search._index_provider
    yield
    codebase_search._index_provider = original


@pytest.fixture(autouse=True)
def _set_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_RAG_EMBEDDING_MODEL", "nomic-embed-text-v1.5")


def _context() -> ToolContext:
    return ToolContext(session_id="sess-1", workspace_root="workspaces/ws")


def _chunk(i: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{i}",
        file_path=f"src/file_{i}.py",
        text=text,
        start_line=i * 10 + 1,
        end_line=i * 10 + 9,
    )


async def _populated_index() -> WorkspaceIndex:
    index = await WorkspaceIndex.open_or_create("ws")
    chunks = [
        _chunk(0, "def validate_auth_token(tok): ..."),
        _chunk(1, "def render_template(ctx): ..."),
        _chunk(2, "class Sandbox: ..."),
    ]
    vectors = np.array(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    await index.add(chunks, vectors)
    return index


def _stub_embed(vector: list[float]) -> Any:
    """Return an ``embed_chunks`` replacement that always yields ``vector`` (as (1, dim))."""

    async def _embed(chunks: list[str], *, model: str, cache_dir: str | None = None) -> np.ndarray:
        return np.array([vector], dtype=np.float32)

    return _embed


def _wire(
    index: WorkspaceIndex | None, monkeypatch: pytest.MonkeyPatch, vector: list[float]
) -> None:
    codebase_search.set_index_provider(lambda ctx: index)
    monkeypatch.setattr(codebase_search, "embed_chunks", _stub_embed(vector))


# --------------------------------------------------------------------------- #
# happy path + result schema
# --------------------------------------------------------------------------- #


async def test_returns_hits_matching_result_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    index = await _populated_index()
    # Query vector aligned with chunk-0 ("validate_auth_token").
    _wire(index, monkeypatch, [0.95, 0.05, 0.0])

    result = await codebase_search.handler(
        {"query": "where do we validate auth tokens"}, _context()
    )

    assert result["query"] == "where do we validate auth tokens"
    assert isinstance(result["hits"], list)
    assert len(result["hits"]) >= 1

    top = result["hits"][0]
    # Shape per result_schema.items.required + optional line fields.
    assert top["path"] == "src/file_0.py"
    assert top["start_line"] == 1
    assert top["end_line"] == 9
    assert isinstance(top["score"], float)
    # Snippet is untrusted-wrapped with provenance.
    assert top["snippet"].startswith("<untrusted_content")
    assert top["snippet"].rstrip().endswith("</untrusted_content>")
    assert 'source="file"' in top["snippet"]
    assert 'path="src/file_0.py"' in top["snippet"]
    assert 'lines="1-9"' in top["snippet"]
    assert "validate_auth_token" in top["snippet"]


async def test_result_validates_against_contract_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import jsonschema  # type: ignore[import-untyped]

    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    index = await _populated_index()
    _wire(index, monkeypatch, [0.0, 1.0, 0.0])

    result = await codebase_search.handler({"query": "render", "top_k": 2}, _context())
    # The handler output must satisfy the descriptor's result_schema (validated in CI).
    jsonschema.validate(instance=result, schema=contract["result_schema"])


async def test_top_k_limits_number_of_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    index = await _populated_index()
    _wire(index, monkeypatch, [1.0, 0.0, 0.0])

    result = await codebase_search.handler({"query": "q", "top_k": 1}, _context())
    assert len(result["hits"]) == 1


async def test_top_k_clamped_to_max(monkeypatch: pytest.MonkeyPatch) -> None:
    index = await _populated_index()
    _wire(index, monkeypatch, [1.0, 0.0, 0.0])
    # 99 is above the schema max (20); handler clamps, index caps at available (3).
    result = await codebase_search.handler({"query": "q", "top_k": 99}, _context())
    assert len(result["hits"]) == 3


# --------------------------------------------------------------------------- #
# empty / unwired index -> empty results (not an error)
# --------------------------------------------------------------------------- #


async def test_empty_index_returns_empty_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = await WorkspaceIndex.open_or_create("ws")
    _wire(empty, monkeypatch, [1.0, 0.0, 0.0])

    result = await codebase_search.handler({"query": "anything"}, _context())
    assert result == {"query": "anything", "hits": []}


async def test_no_index_provider_returns_empty_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default provider (un-wired integrator) yields None -> empty, no embedding call.
    called = False

    async def _should_not_run(
        chunks: list[str], *, model: str, cache_dir: str | None = None
    ) -> Any:
        nonlocal called
        called = True
        return np.empty((0, 0), dtype=np.float32)

    monkeypatch.setattr(codebase_search, "embed_chunks", _should_not_run)

    result = await codebase_search.handler({"query": "anything"}, _context())
    assert result == {"query": "anything", "hits": []}
    assert called is False


async def test_async_index_provider_is_awaited(monkeypatch: pytest.MonkeyPatch) -> None:
    index = await _populated_index()

    async def _async_provider(ctx: ToolContext) -> WorkspaceIndex:
        return index

    codebase_search.set_index_provider(_async_provider)
    monkeypatch.setattr(codebase_search, "embed_chunks", _stub_embed([1.0, 0.0, 0.0]))

    result = await codebase_search.handler({"query": "q"}, _context())
    assert result["hits"][0]["path"] == "src/file_0.py"


# --------------------------------------------------------------------------- #
# bad args / failures
# --------------------------------------------------------------------------- #


async def test_missing_query_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="query"):
        await codebase_search.handler({}, _context())


async def test_blank_query_raises_validation_error() -> None:
    with pytest.raises(ToolValidationError, match="query"):
        await codebase_search.handler({"query": "   "}, _context())


async def test_non_int_top_k_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    index = await _populated_index()
    _wire(index, monkeypatch, [1.0, 0.0, 0.0])
    with pytest.raises(ToolValidationError, match="top_k"):
        await codebase_search.handler({"query": "q", "top_k": "five"}, _context())


async def test_missing_embedding_model_raises_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SKOLL_RAG_EMBEDDING_MODEL", raising=False)
    index = await _populated_index()
    _wire(index, monkeypatch, [1.0, 0.0, 0.0])
    with pytest.raises(ToolExecutionError, match="embedding model"):
        await codebase_search.handler({"query": "q"}, _context())


async def test_embedding_failure_wrapped_as_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = await _populated_index()
    codebase_search.set_index_provider(lambda ctx: index)

    async def _boom(chunks: list[str], *, model: str, cache_dir: str | None = None) -> Any:
        raise RuntimeError("embeddings backend down")

    monkeypatch.setattr(codebase_search, "embed_chunks", _boom)

    with pytest.raises(ToolExecutionError, match="failed to embed query"):
        await codebase_search.handler({"query": "q"}, _context())
