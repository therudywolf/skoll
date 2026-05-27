"""run_bash tool — execute in sandbox. REQUIRES APPROVAL.

Issue: phase-2.4.
Schema: contracts/tools/run_bash.json.
Backed by: skoll.sandbox.session
"""

from __future__ import annotations

from typing import Any


async def handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    NEVER execute on the host. ALWAYS route through the sandbox.

    Steps:
      1. Get / lazily start the sandbox container for context.session_id
      2. Send {action: 'run_bash', command, working_directory, timeout_seconds} over stdin
      3. Collect stdout/stderr (streaming optional — for first cut, buffer)
      4. Truncate at backend-configured max bytes
      5. Return per result_schema
    """
    # TODO(phase-2.4)
    raise NotImplementedError
