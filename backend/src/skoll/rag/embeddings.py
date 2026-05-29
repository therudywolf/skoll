"""Embedding generation via LM Studio.

Issue: phase-1.7.

Uses skoll.lm.client.LMStudioClient.embed.
Caches embeddings keyed by sha256(content + model_id) to avoid recomputation.
"""

from __future__ import annotations

import numpy as np


async def embed_chunks(
    chunks: list[str],
    *,
    model: str,
    cache_dir: str | None = None,
) -> np.ndarray:
    """Return (n_chunks, dim) numpy array."""
    # TODO(phase-1.7)
    raise NotImplementedError
