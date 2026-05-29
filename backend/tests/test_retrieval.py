"""Tests for the in-memory FAISS index + metadata store (Issue 1.8).

Pure FAISS — no network, no LM Studio, no SQLite.
"""

from __future__ import annotations

import numpy as np
import pytest
from skoll.rag.retrieval import Chunk, Hit, WorkspaceIndex


def _chunk(i: int) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{i}",
        file_path=f"src/file_{i}.py",
        text=f"contents of chunk {i}",
        start_line=i * 10 + 1,
        end_line=i * 10 + 9,
    )


async def test_search_returns_nearest_neighbour() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    # Three orthonormal-ish vectors; queries pick out exactly one.
    chunks = [_chunk(0), _chunk(1), _chunk(2)]
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    await index.add(chunks, vectors)

    hits = await index.search(np.array([0.9, 0.1, 0.0], dtype=np.float32), top_k=1)
    assert len(hits) == 1
    top = hits[0]
    assert isinstance(top, Hit)
    assert top.chunk_id == "chunk-0"
    assert top.file_path == "src/file_0.py"
    assert top.snippet == "contents of chunk 0"
    assert top.start_line == 1
    assert top.end_line == 9
    # Cosine similarity is bounded and near 1 for a closely-aligned query.
    assert 0.9 <= top.score <= 1.0001


async def test_search_orders_by_similarity() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    chunks = [_chunk(0), _chunk(1), _chunk(2)]
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    await index.add(chunks, vectors)

    hits = await index.search(np.array([0.0, 1.0, 0.0], dtype=np.float32), top_k=3)
    assert hits[0].chunk_id == "chunk-1"
    # Scores are sorted descending.
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


async def test_top_k_caps_at_available() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([_chunk(0), _chunk(1)], np.eye(2, dtype=np.float32))
    hits = await index.search(np.array([1.0, 0.0], dtype=np.float32), top_k=10)
    assert len(hits) == 2


async def test_empty_index_returns_no_hits() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    hits = await index.search(np.array([1.0, 0.0, 0.0], dtype=np.float32), top_k=5)
    assert hits == []


async def test_incremental_add_accumulates() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([_chunk(0)], np.array([[1.0, 0.0]], dtype=np.float32))
    await index.add([_chunk(1)], np.array([[0.0, 1.0]], dtype=np.float32))
    assert len(index) == 2
    assert index.dim == 2
    hits = await index.search(np.array([0.0, 1.0], dtype=np.float32), top_k=1)
    assert hits[0].chunk_id == "chunk-1"


async def test_query_accepts_2d_shape() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([_chunk(0), _chunk(1)], np.eye(2, dtype=np.float32))
    hits = await index.search(np.array([[1.0, 0.0]], dtype=np.float32), top_k=1)
    assert hits[0].chunk_id == "chunk-0"


async def test_dim_mismatch_on_add_raises() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([_chunk(0)], np.array([[1.0, 0.0]], dtype=np.float32))
    with pytest.raises(ValueError, match="match index dim"):
        await index.add([_chunk(1)], np.array([[1.0, 0.0, 0.0]], dtype=np.float32))


async def test_chunks_vectors_length_mismatch_raises() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    with pytest.raises(ValueError, match="length mismatch"):
        await index.add([_chunk(0), _chunk(1)], np.array([[1.0, 0.0]], dtype=np.float32))


async def test_query_dim_mismatch_raises() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([_chunk(0)], np.array([[1.0, 0.0]], dtype=np.float32))
    with pytest.raises(ValueError, match="match index dim"):
        await index.search(np.array([1.0, 0.0, 0.0], dtype=np.float32), top_k=1)


async def test_add_empty_is_noop() -> None:
    index = await WorkspaceIndex.open_or_create("ws")
    await index.add([], np.empty((0, 0), dtype=np.float32))
    assert len(index) == 0
    assert await index.search(np.array([1.0], dtype=np.float32), top_k=1) == []
