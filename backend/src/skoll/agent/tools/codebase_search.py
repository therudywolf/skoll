"""codebase_search tool — semantic search over indexed workspace.

Issue: phase-1.9.
Schema: contracts/tools/codebase_search.json.
Backed by: skoll.rag.retrieval
"""

from __future__ import annotations

from typing import Any

# from skoll.agent.tools.registry import Tool, ToolContext, ToolSchema  # to be wired


async def handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    args = {query: str, top_k: int = 5, path_filter: str | None}

    Steps:
      1. Resolve workspace_id from context.session_id (one workspace per session for now)
      2. Get FAISS index + metadata via skoll.rag.retrieval.get_index(workspace_id)
      3. Embed `query` via LM Studio embedding model
      4. FAISS search top_k
      5. Hydrate each hit with file_path, line range, snippet
      6. Wrap snippet in <untrusted_content> via skoll.security.untrusted.wrap()
      7. Return per contracts/tools/codebase_search.json result_schema
    """
    # TODO(phase-1.9)
    raise NotImplementedError


# TOOL = Tool(schema=..., handler=handler)   # wire when registry is ready
