"""Token-aware chunking.

Issue: phase-1.6.

Adapted from vendor/ForestOptiLM/parser.py (``chunk_text_semantic``):
  - Segment on paragraph / sentence boundaries, never exceeding ``max_tokens``.
  - Token counts via tiktoken (cl100k_base) — accurate within ~10% for most
    LM Studio models; see AGENTS.md §7.
  - Overlap windowing: the tail of one chunk is repeated at the head of the next,
    sized by ``overlap_tokens``.
  - Each chunk carries stable source offsets (1-based ``start_line`` / ``end_line``)
    and a deterministic id derived from the source text + position.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import tiktoken

# Single shared encoding instance. cl100k_base ships with tiktoken (no network at
# runtime) and is a good proxy for modern model tokenisers.
_ENCODING_NAME = "cl100k_base"
_encoding: tiktoken.Encoding | None = None

# Paragraph splitter (blank line) and sentence splitter (after . ! ?).
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    """A single token-bounded slice of a source document."""

    chunk_id: str
    content: str
    start_line: int
    end_line: int
    token_count: int


def _get_encoding() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(_ENCODING_NAME)
    return _encoding


def count_tokens(text: str) -> int:
    """Count tokens in ``text`` using tiktoken (cl100k_base)."""
    if not text or not text.strip():
        return 0
    return len(_get_encoding().encode(text))


def _segment(text: str, max_tokens: int) -> list[str]:
    """Split text into paragraph/sentence segments, each <= ``max_tokens``.

    A paragraph that fits is kept whole; an oversized paragraph is split on
    sentence boundaries; an oversized *sentence* is left intact here and gets
    hard-split by token window later in :func:`_chunk_segments`.
    """
    segments: list[str] = []
    for raw_para in _PARAGRAPH_RE.split(text):
        para = raw_para.strip()
        if not para:
            continue
        if count_tokens(para) <= max_tokens:
            segments.append(para)
            continue
        current: list[str] = []
        current_tokens = 0
        for sentence in _SENTENCE_RE.split(para):
            sent_tokens = count_tokens(sentence)
            if current and current_tokens + sent_tokens > max_tokens:
                segments.append(" ".join(current))
                current = []
                current_tokens = 0
            current.append(sentence)
            current_tokens += sent_tokens
        if current:
            segments.append(" ".join(current))
    return segments


def _hard_split(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Token-window split for content with no usable paragraph/sentence breaks."""
    enc = _get_encoding()
    tokens = enc.encode(text)
    if not tokens:
        return []
    step = max(1, max_tokens - overlap_tokens)
    pieces: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        pieces.append(enc.decode(tokens[start:end]))
        if end >= len(tokens):
            break
        start += step
    return pieces


def _chunk_segments(segments: list[str], *, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Greedily pack segments into chunks, carrying an overlap segment forward."""
    enc = _get_encoding()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for seg in segments:
        seg_tokens = count_tokens(seg)
        # Segment alone exceeds the budget — flush, then hard-split it.
        if seg_tokens > max_tokens:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0
            chunks.extend(_hard_split(seg, max_tokens, overlap_tokens))
            continue
        if current and current_tokens + seg_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            # Carry the last segment forward as overlap if it fits the overlap budget.
            tail = current[-1]
            if overlap_tokens > 0 and len(enc.encode(tail)) <= overlap_tokens:
                current = [tail]
                current_tokens = count_tokens(tail)
            else:
                current = []
                current_tokens = 0
        current.append(seg)
        current_tokens += seg_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _locate(text: str, snippet: str, search_from: int) -> tuple[int, int]:
    """Return (start_line, end_line), 1-based, for ``snippet`` within ``text``.

    Falls back to the whole-document span when the snippet cannot be located
    verbatim (overlap/whitespace normalisation can perturb exact matches).
    ``search_from`` is a character-offset hint so repeated snippets map to the
    next occurrence rather than always the first.
    """
    idx = text.find(snippet, search_from)
    if idx < 0:
        idx = text.find(snippet)
    if idx < 0:
        total_lines = text.count("\n") + 1
        return 1, total_lines
    start_line = text.count("\n", 0, idx) + 1
    end_line = start_line + snippet.count("\n")
    return start_line, end_line


def chunk_id_for(content: str, *, index: int, source: str = "") -> str:
    """Deterministic 24-char chunk id from source identity + position + content.

    Stable across runs for identical inputs — re-indexing the same file yields
    the same ids (idempotent upserts downstream).
    """
    digest = hashlib.sha256(f"{source}:{index}:{content[:200]}".encode()).hexdigest()
    return digest[:24]


def chunk_text(text: str, *, max_tokens: int, overlap_tokens: int) -> list[Chunk]:
    """Split ``text`` into token-bounded chunks with overlap.

    Each :class:`Chunk` has a token count within ``max_tokens``, a deterministic
    ``chunk_id``, and 1-based ``start_line`` / ``end_line`` offsets into ``text``.
    Returns ``[]`` for empty / whitespace-only input.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")
    if not text or not text.strip():
        return []

    segments = _segment(text, max_tokens)
    raw_chunks = (
        _chunk_segments(segments, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if segments
        else _hard_split(text, max_tokens, overlap_tokens)
    )

    out: list[Chunk] = []
    cursor = 0
    for index, content in enumerate(raw_chunks):
        if not content.strip():
            continue
        start_line, end_line = _locate(text, content, cursor)
        # Advance the search cursor past this chunk's start so overlapping
        # chunks resolve to successive positions.
        found = text.find(content, cursor)
        if found >= 0:
            cursor = found + 1
        out.append(
            Chunk(
                chunk_id=chunk_id_for(content, index=index),
                content=content,
                start_line=start_line,
                end_line=end_line,
                token_count=count_tokens(content),
            )
        )
    return out
