"""FAISS index management + similarity search.

Issue: phase-1.8.

Index lives on disk under .skoll_cache/faiss/<workspace_id>.bin.
Metadata in SQLite (rag_chunks table).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    file_path: str
    start_line: int
    end_line: int
    score: float
    snippet: str


class WorkspaceIndex:
    """One FAISS index per workspace."""

    @classmethod
    async def open_or_create(cls, workspace_id: str) -> WorkspaceIndex:
        # TODO(phase-1.8)
        raise NotImplementedError

    async def add(self, file_path: str, file_hash: str, chunks: list[tuple[str, int, int]]) -> None:
        # TODO(phase-1.8)
        raise NotImplementedError

    async def search(self, query: str, top_k: int) -> list[Hit]:
        # TODO(phase-1.8)
        raise NotImplementedError

    async def remove_file(self, file_path: str) -> None:
        # TODO(phase-3.7)
        raise NotImplementedError
