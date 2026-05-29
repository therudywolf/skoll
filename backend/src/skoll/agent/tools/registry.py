"""Tool registry — loads contracts/tools/*.json and binds them to implementations.

Issue: phase-1.5.

Discovery flow:
  1. On startup, scan contracts/tools/*.json
  2. For each schema, find the Python implementation module at
     skoll.agent.tools.{name} (file must exist)
  3. The module must export `TOOL: Tool` with a name matching the schema
  4. If a tool is enabled for the current phase, register it; otherwise skip with debug log
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSchema:
    """Parsed contracts/tools/<name>.json."""

    name: str
    description: str
    phase: str
    kind: str
    requires_approval: bool
    auto_approve_default: bool
    path_args: list[str]
    parameters: dict[str, Any]
    result_schema: dict[str, Any]


class ToolHandler(Protocol):
    """Each tool implements this async callable."""

    async def __call__(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]: ...


@dataclass
class ToolContext:
    session_id: str
    workspace_root: str
    # Add more fields as tools need them (LM client for sub-calls, sandbox, etc.)


@dataclass(frozen=True)
class Tool:
    schema: ToolSchema
    handler: ToolHandler


class ToolRegistry:
    """Holds all registered tools and produces the JSON Schema list for LM Studio."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    @classmethod
    def load_from_contracts(cls, contracts_dir: str, enabled_phases: set[str]) -> ToolRegistry:
        """Scan contracts/tools/ and register matching implementations."""
        # TODO(phase-1.5)
        raise NotImplementedError

    def register(self, tool: Tool) -> None:
        # TODO(phase-1.5)
        raise NotImplementedError

    def get(self, name: str) -> Tool:
        # TODO
        raise NotImplementedError

    def openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in the OpenAI / LM Studio function-calling format."""
        # TODO(phase-1.5)
        raise NotImplementedError

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        """Validate args, run preflight, invoke handler. Raises ToolError on failure."""
        # TODO(phase-1.5)
        raise NotImplementedError
