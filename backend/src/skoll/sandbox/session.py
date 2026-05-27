"""Per-session sandbox container.

Issue: phase-1.10 + phase-2.4.

Lifecycle:
  - Lazy start on first sandbox-requiring tool call.
  - Idle timeout: 30 min → stop.
  - Explicit shutdown on session close.

Docker SDK preferred over subprocess('docker') — typed errors, no shell.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BashResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


class SandboxSession:
    @classmethod
    async def start(cls, *, session_id: str, workspace_root: str) -> SandboxSession:
        """Launch container, apply network policy, return ready session."""
        # TODO(phase-1.10)
        raise NotImplementedError

    async def run_bash(
        self,
        command: str,
        *,
        working_directory: str = ".",
        timeout_seconds: int = 30,
    ) -> BashResult:
        # TODO(phase-2.4)
        raise NotImplementedError

    async def shutdown(self) -> None:
        # TODO(phase-1.10)
        raise NotImplementedError
