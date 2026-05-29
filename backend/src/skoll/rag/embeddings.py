"""Embedding generation via LM Studio.

Issue: phase-1.7.

Wraps :meth:`skoll.lm.client.LMStudioClient.embed`. An optional on-disk cache,
keyed by ``sha256(content + model)``, lets re-indexing skip already-embedded
chunks (the dominant cost in RAG). Vectors are returned as a single ``float32``
array — the dtype FAISS expects.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from skoll.errors import LMStudioError
from skoll.lm.client import LMStudioClient

# float32 keeps memory/index size down and matches faiss.IndexFlat* expectations.
_DTYPE = np.float32


def _cache_key(content: str, model: str) -> str:
    return hashlib.sha256(f"{content}\x00{model}".encode()).hexdigest()


def _cache_path(cache_dir: Path, content: str, model: str) -> Path:
    return cache_dir / f"{_cache_key(content, model)}.npy"


def _load_cached(path: Path) -> np.ndarray | None:
    if not path.is_file():
        return None
    try:
        vec = np.load(path)
    except (OSError, ValueError):
        return None
    return np.asarray(vec, dtype=_DTYPE).reshape(-1)


async def embed_chunks(
    chunks: list[str],
    *,
    model: str,
    cache_dir: str | None = None,
) -> np.ndarray:
    """Embed ``chunks`` and return an ``(n_chunks, dim)`` ``float32`` array.

    Args:
        chunks: chunk texts to embed (e.g. ``Chunk.content`` values).
        model: the LM Studio embeddings model id (e.g. ``nomic-embed-text-v1.5``).
        cache_dir: optional directory for an on-disk vector cache keyed by
            ``sha256(content + model)``. Cache misses are embedded once and stored.

    Returns:
        An empty ``(0, 0)`` array when ``chunks`` is empty; otherwise ``(n, dim)``.

    Raises:
        LMStudioError: the embedding backend failed or returned ragged vectors.
    """
    if not chunks:
        return np.empty((0, 0), dtype=_DTYPE)

    cache_root: Path | None = None
    if cache_dir is not None:
        cache_root = Path(cache_dir)
        cache_root.mkdir(parents=True, exist_ok=True)

    # Resolve cache hits up front; collect misses (with original positions) to embed.
    vectors: list[np.ndarray | None] = [None] * len(chunks)
    miss_indices: list[int] = []
    miss_texts: list[str] = []
    for i, content in enumerate(chunks):
        if cache_root is not None:
            cached = _load_cached(_cache_path(cache_root, content, model))
            if cached is not None:
                vectors[i] = cached
                continue
        miss_indices.append(i)
        miss_texts.append(content)

    if miss_texts:
        async with LMStudioClient.from_settings() as client:
            raw = await client.embed(miss_texts, model=model)
        for pos, vec in zip(miss_indices, raw, strict=True):
            arr = np.asarray(vec, dtype=_DTYPE).reshape(-1)
            vectors[pos] = arr
            if cache_root is not None:
                np.save(_cache_path(cache_root, chunks[pos], model), arr)

    resolved = [v for v in vectors if v is not None]
    if len(resolved) != len(chunks):
        raise LMStudioError("Embedding failed: missing vectors for one or more chunks")

    dims = {v.shape[0] for v in resolved}
    if len(dims) != 1:
        raise LMStudioError(f"Inconsistent embedding dimensions across chunks: {sorted(dims)}")

    return np.vstack(resolved).astype(_DTYPE, copy=False)
