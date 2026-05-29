"""Unit tests for token-aware chunking (Issue 1.6)."""

from __future__ import annotations

from itertools import pairwise

from skoll.rag.chunking import Chunk, chunk_id_for, chunk_text, count_tokens


def _para(word: str, n: int) -> str:
    return " ".join([word] * n)


def test_empty_and_whitespace_return_no_chunks() -> None:
    assert chunk_text("", max_tokens=100, overlap_tokens=10) == []
    assert chunk_text("   \n\t  \n", max_tokens=100, overlap_tokens=10) == []


def test_short_text_is_single_chunk() -> None:
    text = "A short sentence that easily fits in one chunk."
    chunks = chunk_text(text, max_tokens=100, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].content.strip() == text
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 1
    assert chunks[0].token_count == count_tokens(text)


def test_chunks_stay_within_token_budget() -> None:
    # Several distinct paragraphs, each well under the budget, total over it.
    paragraphs = [_para(f"word{i}", 40) for i in range(20)]
    text = "\n\n".join(paragraphs)
    max_tokens = 64
    chunks = chunk_text(text, max_tokens=max_tokens, overlap_tokens=8)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= max_tokens
        # token_count is consistent with a fresh recount of the content.
        assert chunk.token_count == count_tokens(chunk.content)


def test_oversized_single_paragraph_is_hard_split_within_budget() -> None:
    # One giant paragraph with no sentence breaks → must be token-windowed.
    text = _para("token", 500)
    max_tokens = 50
    chunks = chunk_text(text, max_tokens=max_tokens, overlap_tokens=10)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= max_tokens


def test_overlap_repeats_tail_segment() -> None:
    # Distinct paragraphs so we can detect the carried-over overlap segment.
    paragraphs = [f"Paragraph number {i} has its own unique sentence here." for i in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=20)
    assert len(chunks) >= 2
    # With overlap, the start of a later chunk should re-include the prior chunk's
    # final paragraph for at least one boundary.
    overlaps_found = 0
    for prev, nxt in pairwise(chunks):
        prev_last_para = prev.content.split("\n\n")[-1].strip()
        if nxt.content.strip().startswith(prev_last_para):
            overlaps_found += 1
    assert overlaps_found >= 1


def test_zero_overlap_does_not_repeat() -> None:
    paragraphs = [f"Unique paragraph marker {i} sentence." for i in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=0)
    for prev, nxt in pairwise(chunks):
        prev_last_para = prev.content.split("\n\n")[-1].strip()
        assert not nxt.content.strip().startswith(prev_last_para)


def test_deterministic_ids() -> None:
    text = "\n\n".join(_para(f"word{i}", 30) for i in range(10))
    a = chunk_text(text, max_tokens=48, overlap_tokens=8)
    b = chunk_text(text, max_tokens=48, overlap_tokens=8)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    # Ids are 24-char hex.
    for chunk in a:
        assert len(chunk.chunk_id) == 24
        assert all(ch in "0123456789abcdef" for ch in chunk.chunk_id)


def test_chunk_id_for_is_stable_and_position_sensitive() -> None:
    assert chunk_id_for("hello", index=0) == chunk_id_for("hello", index=0)
    assert chunk_id_for("hello", index=0) != chunk_id_for("hello", index=1)
    assert chunk_id_for("hello", index=0, source="a.py") != chunk_id_for("hello", index=0)


def test_line_offsets_point_into_source() -> None:
    text = "\n\n".join(f"Distinct paragraph {i} text body." for i in range(8))
    lines = text.splitlines()
    chunks = chunk_text(text, max_tokens=32, overlap_tokens=4)
    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)


def test_invalid_arguments_raise() -> None:
    import pytest

    with pytest.raises(ValueError):
        chunk_text("x", max_tokens=0, overlap_tokens=0)
    with pytest.raises(ValueError):
        chunk_text("x", max_tokens=10, overlap_tokens=-1)
    with pytest.raises(ValueError):
        chunk_text("x", max_tokens=10, overlap_tokens=10)


def test_chunk_is_frozen_dataclass() -> None:
    import dataclasses

    c = Chunk(chunk_id="abc", content="x", start_line=1, end_line=1, token_count=1)
    assert dataclasses.is_dataclass(c)
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        c.content = "y"  # type: ignore[misc]
