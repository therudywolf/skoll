"""FAISS index management + similarity search.

Issue: phase-1.8.

This batch keeps BOTH the FAISS vector index AND the chunk metadata store
**in memory**. Persistence (FAISS file under ``.skoll_cache/faiss`` + a
``rag_chunks`` SQLite table) is a later task — see the TODO below. Nothing here
imports ``skoll.db``.

The index uses inner-product over L2-normalised vectors, i.e. cosine similarity
(same approach as vendor/ForestOptiLM/retrieval.py). ``score`` is the cosine
similarity in ``[-1, 1]``; higher is closer.
"""

from __future__ import annotations

from dataclasses import dataclass

import faiss
import numpy as np

# float32 is what faiss.IndexFlat* requires.
_DTYPE = np.float32


@dataclass(frozen=True)
class Chunk:
    """Input record for :meth:`WorkspaceIndex.add` — one chunk + its provenance."""

    chunk_id: str
    file_path: str
    text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Hit:
    """A search result. Carries enough to cite the source and render a snippet."""

    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    score: float
    snippet: str


def _normalised(vectors: np.ndarray) -> np.ndarray:
    """Return a contiguous float32 copy with each row L2-normalised in place."""
    arr = np.ascontiguousarray(vectors, dtype=_DTYPE)
    if arr.ndim != 2:
        raise ValueError(f"vectors must be 2-D (n, dim); got shape {arr.shape}")
    faiss.normalize_L2(arr)
    return arr


class WorkspaceIndex:
    """One in-memory FAISS index + metadata store per workspace.

    Vectors live in a ``faiss.IndexFlatIP``; the parallel ``_meta`` list maps each
    FAISS row to its :class:`Chunk` provenance. The two stay index-aligned: row ``i``
    in FAISS corresponds to ``_meta[i]``.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self._index: faiss.IndexFlatIP | None = None
        self._dim: int | None = None
        # TODO(phase-1.8): persist metadata to SQLite (db models). In-memory for now.
        self._meta: list[Chunk] = []

    @classmethod
    async def open_or_create(cls, workspace_id: str) -> WorkspaceIndex:
        """Create a fresh in-memory index for ``workspace_id``.

        Async to match the eventual disk-backed implementation; today it never
        performs I/O.
        """
        return cls(workspace_id)

    @property
    def dim(self) -> int | None:
        """Embedding dimensionality, or ``None`` before the first :meth:`add`."""
        return self._dim

    def __len__(self) -> int:
        return len(self._meta)

    async def add(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        """Add ``chunks`` and their embedding ``vectors`` to the index.

        ``vectors`` is an ``(n, dim)`` array aligned with ``chunks``. The first call
        fixes the index dimensionality; later calls must match it.
        """
        if len(chunks) == 0:
            return
        arr = _normalised(vectors)
        if arr.shape[0] != len(chunks):
            raise ValueError(
                f"chunks/vectors length mismatch: {len(chunks)} chunks, {arr.shape[0]} vectors"
            )
        dim = int(arr.shape[1])
        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)
            self._dim = dim
        elif dim != self._dim:
            raise ValueError(f"vector dim {dim} does not match index dim {self._dim}")
        self._index.add(arr)
        self._meta.extend(chunks)

    async def search(self, query_vector: np.ndarray, top_k: int) -> list[Hit]:
        """Return up to ``top_k`` nearest chunks to ``query_vector`` (cosine sim).

        ``query_vector`` may be 1-D ``(dim,)`` or 2-D ``(1, dim)``. Returns ``[]``
        when the index is empty.
        """
        if self._index is None or not self._meta or top_k <= 0:
            return []
        q = np.asarray(query_vector, dtype=_DTYPE).reshape(1, -1)
        if self._dim is not None and q.shape[1] != self._dim:
            raise ValueError(f"query vector dim {q.shape[1]} does not match index dim {self._dim}")
        q = _normalised(q)
        k = min(top_k, len(self._meta))
        scores, indices = self._index.search(q, k)
        hits: list[Hit] = []
        for score, idx in zip(scores[0], indices[0], strict=True):
            if idx < 0 or idx >= len(self._meta):
                continue
            meta = self._meta[int(idx)]
            hits.append(
                Hit(
                    chunk_id=meta.chunk_id,
                    file_path=meta.file_path,
                    start_line=meta.start_line,
                    end_line=meta.end_line,
                    score=float(score),
                    snippet=meta.text,
                )
            )
        return hits

    async def remove_file(self, file_path: str) -> None:
        # TODO(phase-3.7): incremental re-index needs id-mapped FAISS + persistence.
        raise NotImplementedError
