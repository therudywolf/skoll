"""write_file tool. REQUIRES APPROVAL.

Issue: phase-2.2.
Schema: contracts/tools/write_file.json.
"""

from __future__ import annotations

from typing import Any


async def handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Approval flow is handled by AgentLoop before this is called; by the time
    handler() runs, the user (or auto-approve setting) has consented.

    Steps:
      1. skoll.security.path.safe_resolve()
      2. Atomic write: tmp file + rename
      3. Update file watcher / RAG re-index queue
      4. Return per result_schema
    """
    # TODO(phase-2.2)
    raise NotImplementedError
