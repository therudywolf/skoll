"""run_bash tool — execute in sandbox. REQUIRES APPROVAL.

Issue: phase-2.4.
Schema: contracts/tools/run_bash.json.
Backed by: skoll.sandbox.session (``SandboxSession.run_bash``).

NEVER executes on the host — the command always runs inside the per-session
sandbox container (``bash -lc`` under gVisor, unprivileged, egress-allowlisted).

The integrator seam
-------------------
The container is per-session and owned by the session/sandbox lifecycle, which
this module does not control. :class:`~skoll.agent.tools.registry.ToolContext`
exposes only ``session_id`` / ``workspace_root``, so we expose a provider seam
(mirroring ``codebase_search.set_index_provider``):

    set_sandbox_provider(provider)

where ``provider(context) -> SandboxSession`` resolves the live sandbox for a
``ToolContext`` (sync or async). The integrator wires this once at startup (e.g.
from a session→SandboxSession map that lazily ``SandboxSession.start``s the
container). Until it is wired, the default provider raises
``SandboxStartError('sandbox not wired')`` — exec must fail loud, never silently
fall back to the host.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Final

from skoll.errors import SandboxStartError, ToolExecutionError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from skoll.agent.tools.registry import ToolContext
    from skoll.sandbox.session import SandboxSession

    SandboxProvider = Callable[[ToolContext], "SandboxSession | Awaitable[SandboxSession]"]

# Contract bounds (contracts/tools/run_bash.json → parameters.timeout_seconds).
_MIN_TIMEOUT_SECONDS: Final[int] = 1
_MAX_TIMEOUT_SECONDS: Final[int] = 300

# Ceiling on captured stdout/stderr returned to the model (the sandbox already caps
# at 4 MiB when decoding; this is a tighter prompt-safety cap for the tool result).
_MAX_STREAM_CHARS: Final[int] = 64 * 1024


async def _default_sandbox_provider(context: ToolContext) -> SandboxSession:
    """Fallback provider used until the integrator wires a real one.

    Raises ``SandboxStartError`` so an un-wired deployment fails loudly rather than
    risking host execution.
    """
    raise SandboxStartError(
        "sandbox not wired: call skoll.agent.tools.run_bash.set_sandbox_provider() at startup"
    )


# Module-level seam. Reassigned by the integrator via :func:`set_sandbox_provider`.
_sandbox_provider: SandboxProvider = _default_sandbox_provider


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """Install the function that resolves a :class:`ToolContext` to its ``SandboxSession``.

    Wired once at startup by the integrator. ``provider`` may be sync or async; it
    should return a started :class:`~skoll.sandbox.session.SandboxSession` (lazily
    starting the container is fine).
    """
    global _sandbox_provider
    _sandbox_provider = provider


async def _resolve_sandbox(context: ToolContext) -> SandboxSession:
    """Invoke the configured provider, awaiting it if it returns an awaitable."""
    result = _sandbox_provider(context)
    if inspect.isawaitable(result):
        return await result
    return result


def _truncate(text: str) -> str:
    """Clamp a captured stream to ``_MAX_STREAM_CHARS`` with a visible marker."""
    if len(text) <= _MAX_STREAM_CHARS:
        return text
    return text[:_MAX_STREAM_CHARS] + "\n…[output truncated]"


def _coerce_timeout(raw: object) -> int | None:
    """Clamp the optional ``timeout_seconds`` into the contract's [1, 300] range.

    ``None`` is returned when absent so the sandbox applies its own configured
    default (``SKOLL_SANDBOX_BASH_TIMEOUT_SECONDS``).
    """
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolExecutionError("run_bash: 'timeout_seconds' must be an integer")
    return max(_MIN_TIMEOUT_SECONDS, min(_MAX_TIMEOUT_SECONDS, raw))


async def handler(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Run a shell command in the session's sandbox; return per result_schema.

    args = {command: str, working_directory?: str (default '.'), timeout_seconds?: int, reason: str}

    Steps:
      1. Resolve the session's :class:`SandboxSession` via the wired provider.
      2. ``SandboxSession.run_bash(command, working_directory, timeout_seconds)`` —
         executes ``bash -lc`` inside the container (never on the host).
      3. Truncate stdout/stderr for prompt safety.
      4. Return ``{exit_code, stdout, stderr, duration_ms, timed_out}``.

    Raises:
        SandboxStartError: the provider is un-wired or the container is unavailable.
        ToolExecutionError: ``command`` missing / bad timeout, or the sandbox errored.
    """
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolExecutionError("run_bash: 'command' is required and must be a non-empty string")

    working_directory = args.get("working_directory")
    if working_directory is None:
        working_directory = "."
    elif not isinstance(working_directory, str):
        raise ToolExecutionError("run_bash: 'working_directory' must be a string")

    timeout_seconds = _coerce_timeout(args.get("timeout_seconds"))

    sandbox = await _resolve_sandbox(context)
    try:
        result = await sandbox.run_bash(
            command,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
        )
    except SandboxStartError:
        raise
    except Exception as exc:  # normalise any sandbox/runtime failure to a tool error
        raise ToolExecutionError(f"run_bash: sandbox execution failed: {exc}") from exc

    return {
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
    }
