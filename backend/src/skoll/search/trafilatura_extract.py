"""Trafilatura fallback for read_url when Jina is unavailable.

Issue: phase-2.7.

Trafilatura works well on static HTML; not great on heavy SPAs (use Jina for those).
"""

from __future__ import annotations

from skoll.search.jina_reader import ReadResult


async def read(url: str, *, max_chars: int = 10_000) -> ReadResult:
    # TODO(phase-2.7)
    raise NotImplementedError
