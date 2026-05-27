"""Token-aware chunking.

Issue: phase-1.6.

Adapt vendor/ForestOptiLM/forestoptilm/chunking.py:
  - Same algorithm, same defaults
  - Use tiktoken for token counts (works for most LM Studio models within ±10%)
  - Add overlap windowing per settings.rag.chunk_overlap_tokens
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    content: str
    start_line: int
    end_line: int
    token_count: int


def chunk_text(text: str, *, max_tokens: int, overlap_tokens: int) -> list[Chunk]:
    # TODO(phase-1.6)
    raise NotImplementedError
