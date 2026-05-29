"""codebase_search tool — semantic search over indexed workspace.

Issue: phase-1.9.
Schema: contracts/tools/codebase_search.json.
Backed by: skoll.rag.retrieval (WorkspaceIndex), skoll.rag.embeddings (embed_chunks),
skoll.security.untrusted (wrap).

This tool is **read-only** (``requires_approval: false`` / ``auto_approve_default: true``
in the descriptor): it never mutates the workspace, so it auto-approves.

The integrator seam
-------------------
The handler needs the *populated* :class:`~skoll.rag.retrieval.WorkspaceIndex` for the
session's workspace. As of phase-1.8 that index is held in memory by whoever ran
``POST /api/workspaces/{id}/index`` — there is **no** global registry in
``skoll.rag.retrieval`` (``WorkspaceIndex.open_or_create`` builds a *fresh, empty* index)
and :class:`~skoll.agent.tools.registry.ToolContext` exposes only ``session_id`` /
``workspace_root`` (neither of which I own). So this module exposes a small provider seam:

    set_index_provider(provider)

where ``provider(context) -> WorkspaceIndex | None`` returns the live index for a
``ToolContext`` (or ``None`` when nothing has been indexed yet). The integrator wires this
once at startup (e.g. from the indexing service / app state) so the handler can reach the
real index without importing app/registry internals. Until it is wired, the default
provider returns ``None`` and the tool degrades gracefully to "no hits" rather than raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skoll.config import get_settings
from skoll.errors import ToolExecutionError, ToolValidationError
from skoll.rag.embeddings import embed_chunks
from skoll.security.untrusted import wrap

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from skoll.agent.tools.registry import ToolContext
    from skoll.rag.retrieval import Hit, WorkspaceIndex

# Mirrors contracts/tools/codebase_search.json -> parameters.properties.top_k.
_DEFAULT_TOP_K = 5
_MIN_TOP_K = 1
_MAX_TOP_K = 20

# A provider maps a ToolContext to the live WorkspaceIndex for its session/workspace.
# Sync or async returns are both accepted so the integrator can back it with either an
# in-memory dict lookup or an awaitable ``WorkspaceIndex.open_or_create``-style call.
if TYPE_CHECKING:
    IndexProvider = Callable[
        [ToolContext], "WorkspaceIndex | None | Awaitable[WorkspaceIndex | None]"
    ]


async def _default_index_provider(context: ToolContext) -> WorkspaceIndex | None:
    """Fallback provider used until the integrator wires a real one.

    Returns ``None`` so an un-wired deployment yields empty results instead of erroring.
    """
    return None


# Module-level seam. Reassigned by the integrator via :func:`set_index_provider`.
_index_provider: IndexProvider = _default_index_provider


def set_index_provider(provider: IndexProvider) -> None:
    """Install the function that resolves a :class:`ToolContext` to its ``WorkspaceIndex``.

    Wired once at startup by the integrator. ``provider`` may be sync or async and should
    return ``None`` when the session's workspace has not been indexed yet.
    """
    global _index_provider
    _index_provider = provider


async def _resolve_index(context: ToolContext) -> WorkspaceIndex | None:
    """Invoke the configured provider, awaiting it if it returns an awaitable."""
    import inspect

    result = _index_provider(context)
    if inspect.isawaitable(result):
        return await result
    return result


def _coerce_top_k(raw: object) -> int:
    """Clamp ``top_k`` into the descriptor's [1, 20] range; default when absent.

    The registry validates args against the JSON Schema before we run, so this is a
    defensive belt-and-braces clamp (and lets the handler stay correct if called directly
    in a test without the registry).
    """
    if raw is None:
        return _DEFAULT_TOP_K
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolValidationError("codebase_search: 'top_k' must be an integer")
    return max(_MIN_TOP_K, min(_MAX_TOP_K, raw))


def _hit_to_result(hit: Hit) -> dict[str, Any]:
    """Shape one :class:`Hit` per the descriptor's result_schema.items.

    The snippet is untrusted file content, so it is wrapped in ``<untrusted_content>`` with
    provenance (path + line range) before it can reach the model's prompt.
    """
    snippet = wrap(
        hit.snippet,
        source="file",
        path=hit.file_path,
        lines=f"{hit.start_line}-{hit.end_line}",
    )
    return {
        "path": hit.file_path,
        "start_line": hit.start_line,
        "end_line": hit.end_line,
        "score": hit.score,
        "snippet": snippet,
    }


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Semantic search over the session's indexed workspace.

    args = {query: str, top_k?: int (1..20, default 5), path_filter?: str}

    Steps:
      1. Validate ``query`` and clamp ``top_k``.
      2. Resolve the session's :class:`WorkspaceIndex` via the integrator-wired provider
         (see module docstring). Missing / empty index -> ``{"query": ..., "hits": []}``.
      3. Embed ``query`` with the configured RAG embedding model.
      4. FAISS top-k search over the index (cosine similarity).
      5. Wrap each snippet in ``<untrusted_content>`` and shape per the result_schema.

    Returns a dict matching contracts/tools/codebase_search.json -> result_schema:
        {"query": str, "hits": [{path, start_line, end_line, score, snippet}, ...]}

    Raises:
        ToolValidationError: ``query`` missing/blank or ``top_k`` not an int.
        ToolExecutionError: the embeddings backend / index search failed.
    """
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolValidationError(
            "codebase_search: 'query' is required and must be a non-empty string"
        )
    top_k = _coerce_top_k(args.get("top_k"))

    index = await _resolve_index(context)
    # No index wired, or nothing indexed yet -> empty result (not an error).
    if index is None or len(index) == 0:
        return {"query": query, "hits": []}

    embedding_model = get_settings().rag.embedding_model
    if not embedding_model:
        raise ToolExecutionError(
            "codebase_search: no RAG embedding model configured (set SKOLL_RAG_EMBEDDING_MODEL)"
        )

    try:
        query_vectors = await embed_chunks([query], model=embedding_model)
    except Exception as exc:  # normalise any backend failure to a tool error
        raise ToolExecutionError(f"codebase_search: failed to embed query: {exc}") from exc

    if query_vectors.shape[0] == 0:
        return {"query": query, "hits": []}

    try:
        hits: list[Hit] = await index.search(query_vectors[0], top_k)
    except Exception as exc:
        raise ToolExecutionError(f"codebase_search: index search failed: {exc}") from exc

    return {"query": query, "hits": [_hit_to_result(hit) for hit in hits]}
