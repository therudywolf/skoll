"""Tool registry — loads contracts/tools/*.json and binds them to implementations.

Issue: phase-1.5.

Discovery flow:
  1. On startup, scan contracts/tools/*.json
  2. For each schema, find the Python implementation module at
     skoll.agent.tools.{name} (file must exist)
  3. The module must export an async ``handler`` callable
  4. If a tool is enabled for the current phase, register it; otherwise skip with debug log
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import jsonschema  # type: ignore[import-untyped]  # no stubs shipped; treated as Any
import structlog
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    SchemaError as _JSONSchemaError,
)
from jsonschema.exceptions import (
    ValidationError as _JSONValidationError,
)

from skoll.errors import ToolError, ToolValidationError

logger = structlog.get_logger(__name__)

# Package holding the per-tool implementation modules (skoll.agent.tools.<name>).
_TOOLS_PACKAGE = "skoll.agent.tools"


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


def _parse_schema(path: Path) -> ToolSchema:
    """Parse one contracts/tools/<name>.json into a ToolSchema.

    Raises ToolError if the file is not valid JSON or is missing required fields.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"tool descriptor {path.name} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ToolError(f"tool descriptor {path.name} must be a JSON object")

    required = (
        "name",
        "description",
        "phase",
        "kind",
        "requires_approval",
        "auto_approve_default",
        "path_args",
        "parameters",
        "result_schema",
    )
    missing = [field for field in required if field not in raw]
    if missing:
        raise ToolError(f"tool descriptor {path.name} is missing fields: {', '.join(missing)}")

    return ToolSchema(
        name=str(raw["name"]),
        description=str(raw["description"]),
        phase=str(raw["phase"]),
        kind=str(raw["kind"]),
        requires_approval=bool(raw["requires_approval"]),
        auto_approve_default=bool(raw["auto_approve_default"]),
        path_args=[str(arg) for arg in raw["path_args"]],
        parameters=dict(raw["parameters"]),
        result_schema=dict(raw["result_schema"]),
    )


def _bind_handler(name: str) -> ToolHandler:
    """Import skoll.agent.tools.<name> and return its ``handler`` callable.

    Raises ToolError if the module does not exist or exports no callable ``handler``.
    """
    module_name = f"{_TOOLS_PACKAGE}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ToolError(f"tool '{name}' has no implementation module ({module_name})") from exc

    handler = getattr(module, "handler", None)
    if not callable(handler):
        raise ToolError(f"tool '{name}' module {module_name} exports no callable 'handler'")

    return cast("ToolHandler", handler)


class ToolRegistry:
    """Holds all registered tools and produces the JSON Schema list for LM Studio."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    @classmethod
    def load_from_contracts(cls, contracts_dir: str, enabled_phases: set[str]) -> ToolRegistry:
        """Scan contracts/tools/ and register matching implementations.

        For each ``*.json`` descriptor: parse it, skip (with a debug log) any tool whose phase
        is not in ``enabled_phases``, otherwise import ``skoll.agent.tools.<name>`` and bind its
        ``handler``. A descriptor whose module is missing or exports no ``handler`` is rejected
        with a ToolError.
        """
        directory = Path(contracts_dir)
        if not directory.is_dir():
            raise ToolError(f"contracts dir does not exist: {contracts_dir}")

        registry = cls()
        for path in sorted(directory.glob("*.json")):
            schema = _parse_schema(path)

            if schema.phase not in enabled_phases:
                logger.debug(
                    "skoll.tool_registry.skip_phase",
                    tool=schema.name,
                    phase=schema.phase,
                    enabled_phases=sorted(enabled_phases),
                )
                continue

            handler = _bind_handler(schema.name)
            registry.register(Tool(schema=schema, handler=handler))
            logger.debug(
                "skoll.tool_registry.registered",
                tool=schema.name,
                phase=schema.phase,
                kind=schema.kind,
            )

        return registry

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry. Raises ToolError on a duplicate name."""
        name = tool.schema.name
        if name in self._tools:
            raise ToolError(f"tool '{name}' is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        """Look up a registered tool by name. Raises ToolError if unknown."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool: {name!r}") from exc

    def names(self) -> list[str]:
        """Return the sorted names of all registered tools."""
        return sorted(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in the OpenAI / LM Studio function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.schema.name,
                    "description": tool.schema.description,
                    "parameters": tool.schema.parameters,
                },
            }
            for tool in (self._tools[name] for name in sorted(self._tools))
        ]

    def validate_args(self, name: str, args: dict[str, Any]) -> None:
        """Validate ``args`` against the tool's ``parameters`` JSON Schema.

        Raises ToolError if the tool is unknown, or ToolValidationError if the arguments do not
        satisfy the schema (or the schema itself is malformed).
        """
        tool = self.get(name)
        try:
            jsonschema.validate(instance=args, schema=tool.schema.parameters)
        except _JSONValidationError as exc:
            raise ToolValidationError(
                f"invalid arguments for tool '{name}': {exc.message}"
            ) from exc
        except _JSONSchemaError as exc:
            raise ToolValidationError(
                f"tool '{name}' has an invalid parameter schema: {exc.message}"
            ) from exc

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
    ) -> dict[str, Any]:
        """Validate args, run preflight, invoke handler. Raises ToolError on failure."""
        tool = self.get(name)
        self.validate_args(name, args)
        return await tool.handler(args, context)
