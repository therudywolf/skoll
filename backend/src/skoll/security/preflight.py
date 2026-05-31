"""Pre-tool-call security check pipeline.

Issue: phase-1.* (used by every tool execution).

See docs/THREAT_MODEL.md → 'Required pre-tool-call checks'.

Order (first failure short-circuits with ``REJECT``):
  1. JSON Schema validation of args against ``tool.schema.parameters``
  2. Path validation for every ``tool.schema.path_args`` (``safe_resolve``)
  3. Shell sanitization for ``kind == 'shell'``
  4. URL allowlist hook for ``kind == 'url_fetch'`` (the web agent owns the actual
     allowlist; we only structure the seam here — see ``_check_url_fetch``)
  5. Approval gate: ``NEEDS_APPROVAL`` when the tool requires approval and the
     session has not auto-approved it, otherwise ``OK``

Rate limiting (step 5 in the THREAT_MODEL pseudo-code) is owned by the agent loop /
API layer and is intentionally NOT implemented here — preflight stays a pure,
side-effect-light gate that the loop can call synchronously before every tool run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

import jsonschema  # type: ignore[import-untyped]  # no stubs shipped; treated as Any
import structlog
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    SchemaError as _JSONSchemaError,
)
from jsonschema.exceptions import (
    ValidationError as _JSONValidationError,
)

from skoll.errors import PathOutsideWorkspaceError
from skoll.security.path import safe_resolve

if TYPE_CHECKING:
    from skoll.agent.tools.registry import Tool

logger = structlog.get_logger(__name__)

# NUL bytes can truncate/confuse the docker-exec argv that ``run_bash`` builds; an
# empty command is meaningless. These are the only *host-side* shell rejections —
# ordinary shell metacharacters (``|``, ``&&``, ``>``…) are legitimate because the
# command is executed by *bash inside the sandbox*, never by a host shell.
_SHELL_FORBIDDEN_CHARS: frozenset[str] = frozenset({"\x00"})


class PreflightResult(Enum):
    OK = "ok"
    NEEDS_APPROVAL = "needs_approval"
    REJECT = "reject"


@dataclass
class PreflightReport:
    result: PreflightResult
    sanitized_args: dict[str, Any]
    rejection_reason: str | None


class PreflightSession(Protocol):
    """Structural contract for the ``session`` preflight needs.

    The concrete type is the DB session model (phase-1.15); preflight only reads:

    * ``workspace_root`` — the root every path is validated against.
    * ``auto_approve`` — per-session, per-tool opt-in (``{tool_name: bool}``).
      Absent / falsy ⇒ the tool still needs approval.
    * ``allowlist`` — egress hosts for ``url_fetch`` tools (consumed by the web
      agent's allowlist check; preflight only forwards it).

    All are optional at runtime (read with ``getattr``) so an early-phase caller
    can pass a lightweight stand-in.
    """

    workspace_root: str
    auto_approve: dict[str, bool]
    allowlist: object


def _reject(args: dict[str, Any], reason: str) -> PreflightReport:
    return PreflightReport(
        result=PreflightResult.REJECT, sanitized_args=args, rejection_reason=reason
    )


def _validate_schema(tool: Tool, args: dict[str, Any]) -> str | None:
    """Return a rejection reason if ``args`` violate the tool's JSON Schema, else None."""
    try:
        jsonschema.validate(instance=args, schema=tool.schema.parameters)
    except _JSONValidationError as exc:
        return f"invalid arguments for tool {tool.schema.name!r}: {exc.message}"
    except _JSONSchemaError as exc:
        return f"tool {tool.schema.name!r} has an invalid parameter schema: {exc.message}"
    return None


def _validate_paths(tool: Tool, args: dict[str, Any], workspace_root: str) -> str | None:
    """Resolve every declared path arg; return a rejection reason on the first escape."""
    for path_arg in tool.schema.path_args:
        raw = args.get(path_arg)
        if raw is None:
            # Optional path arg not supplied — nothing to validate.
            continue
        if not isinstance(raw, str):
            return f"path argument {path_arg!r} must be a string"
        try:
            safe_resolve(raw, workspace_root)
        except PathOutsideWorkspaceError as exc:
            return f"{path_arg}: {exc}"
    return None


def _check_shell(args: dict[str, Any]) -> str | None:
    """Reject host-hostile control sequences in a shell command.

    The command itself runs inside the sandbox under ``bash -lc`` (shell expansion
    is *contained* there), so we do not strip ordinary shell syntax. We only reject
    a missing/empty command and NUL bytes that could corrupt the docker-exec argv.
    """
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return "shell command is required and must be a non-empty string"
    if any(ch in command for ch in _SHELL_FORBIDDEN_CHARS):
        return "shell command contains forbidden control characters"
    return None


def _check_url_fetch(args: dict[str, Any], session: Any) -> str | None:  # noqa: ANN401
    """Hook for the egress allowlist of ``url_fetch`` tools.

    The actual allowlist enforcement lives with the web agent (``skoll.search``);
    we deliberately do NOT import it here. This seam validates the URL is present
    and a string so a later allowlist check has something well-formed to act on.
    When that check is wired, it should consume ``getattr(session, 'allowlist', None)``.
    """
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return "url is required and must be a non-empty string"
    return None


async def check_tool_call(
    tool: Tool,
    args: dict[str, Any],
    session: Any,  # noqa: ANN401 — DB Session model, typed in phase-1.15 (see PreflightSession)
) -> PreflightReport:
    """Run all preflight checks in order; first failure short-circuits with ``REJECT``.

    Returns a :class:`PreflightReport`:
      * ``REJECT`` (+ reason) on a schema/path/shell/url violation.
      * ``NEEDS_APPROVAL`` when ``tool.schema.requires_approval`` and the session has
        not auto-approved this tool.
      * ``OK`` otherwise.

    ``sanitized_args`` is currently the input ``args`` unchanged (path/shell checks
    are validate-only — they reject rather than rewrite); the field exists so a
    future sanitiser can hand back a normalised copy without changing the signature.
    """
    name = tool.schema.name

    reason = _validate_schema(tool, args)
    if reason is not None:
        logger.info("skoll.preflight.reject", tool=name, stage="schema")
        return _reject(args, reason)

    workspace_root = str(getattr(session, "workspace_root", "") or "")
    if tool.schema.path_args:
        if not workspace_root:
            logger.info("skoll.preflight.reject", tool=name, stage="path")
            return _reject(args, "session has no workspace_root; cannot validate paths")
        reason = _validate_paths(tool, args, workspace_root)
        if reason is not None:
            logger.info("skoll.preflight.reject", tool=name, stage="path")
            return _reject(args, reason)

    if tool.schema.kind == "shell":
        reason = _check_shell(args)
        if reason is not None:
            logger.info("skoll.preflight.reject", tool=name, stage="shell")
            return _reject(args, reason)

    if tool.schema.kind == "url_fetch":
        reason = _check_url_fetch(args, session)
        if reason is not None:
            logger.info("skoll.preflight.reject", tool=name, stage="url_fetch")
            return _reject(args, reason)

    if tool.schema.requires_approval:
        auto_approve = getattr(session, "auto_approve", {}) or {}
        approved = bool(auto_approve.get(name, False)) if isinstance(auto_approve, dict) else False
        if not approved:
            logger.info("skoll.preflight.needs_approval", tool=name)
            return PreflightReport(
                result=PreflightResult.NEEDS_APPROVAL,
                sanitized_args=args,
                rejection_reason=None,
            )

    return PreflightReport(result=PreflightResult.OK, sanitized_args=args, rejection_reason=None)
