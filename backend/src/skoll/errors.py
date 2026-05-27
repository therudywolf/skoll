"""Custom exception hierarchy. NEVER raise bare Exception in business logic."""

from __future__ import annotations


class SkollError(Exception):
    """Base class for all Skoll errors."""

    code: str = "skoll.unknown"


class ConfigError(SkollError):
    code = "config.invalid"


class LMStudioError(SkollError):
    code = "lmstudio.error"


class LMStudioUnreachableError(LMStudioError):
    code = "lmstudio.unreachable"


class LMStudioAuthError(LMStudioError):
    code = "lmstudio.auth"


class ToolError(SkollError):
    code = "tool.error"


class ToolValidationError(ToolError):
    code = "tool.invalid_arguments"


class ToolExecutionError(ToolError):
    code = "tool.execution_failed"


class ToolRejectedError(ToolError):
    code = "tool.rejected_by_user"


class PreflightError(SkollError):
    code = "preflight.failed"


class PathOutsideWorkspaceError(PreflightError):
    code = "preflight.path_outside_workspace"


class SandboxError(SkollError):
    code = "sandbox.error"


class SandboxStartError(SandboxError):
    code = "sandbox.start_failed"


class SandboxTimeoutError(SandboxError):
    code = "sandbox.timeout"


class AgentLoopError(SkollError):
    code = "agent.loop_error"


class MaxIterationsExceededError(AgentLoopError):
    code = "agent.max_iterations"


class StreamRecoveryFailedError(AgentLoopError):
    code = "agent.stream_recovery_failed"
