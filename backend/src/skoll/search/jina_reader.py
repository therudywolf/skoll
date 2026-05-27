"""Jina Reader — URL → markdown.

Issue: phase-2.7.

Free tier 50K/mo without API key. With API key: higher limit + internal proxy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadResult:
    url: str
    title: str
    content: str  # markdown
    source: str  # 'jina'
    truncated: bool


async def read(url: str, *, max_chars: int = 10_000, api_key: str = "") -> ReadResult:
    # TODO(phase-2.7)
    raise NotImplementedError
