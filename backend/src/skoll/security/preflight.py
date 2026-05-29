"""Pre-tool-call security check pipeline.

Issue: phase-1.* (used by every tool execution).

See docs/THREAT_MODEL.md → 'Required pre-tool-call checks'.

Order:
  1. JSON Schema validation of args
  2. Path validation for path_args declared in the schema
  3. Shell sanitization for kind='shell'
  4. URL allowlist for kind='url_fetch'
  5. Rate limit
  6. Approval gate
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skoll.agent.tools.registry import Tool


class PreflightResult(Enum):
    OK = "ok"
    NEEDS_APPROVAL = "needs_approval"
    REJECT = "reject"


@dataclass
class PreflightReport:
    result: PreflightResult
    sanitized_args: dict[str, Any]
    rejection_reason: str | None


async def check_tool_call(
    tool: Tool,
    args: dict[str, Any],
    session: Any,  # noqa: ANN401 — DB Session model, typed in phase-1.15
) -> PreflightReport:
    """Run all preflight checks. Logs each to db.preflight_log."""
    # TODO(phase-1)
    raise NotImplementedError
