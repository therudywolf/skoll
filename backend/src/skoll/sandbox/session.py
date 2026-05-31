"""Per-session sandbox container — host-side controller.

Issue: phase-1.10 (infra) + phase-2.4 (``run_bash`` tool that drives ``exec``).

Lifecycle:
  - Lazy start on first sandbox-requiring tool call (``SandboxSession.start``).
  - Commands run via ``docker exec`` against a long-lived, idle container.
  - Explicit shutdown on session close (``stop`` / ``shutdown``).

Design notes
------------
We drive the ``docker`` CLI with **list-form argv** through
``asyncio.create_subprocess_exec`` (NEVER ``shell=True`` — Golden Rule #1; no
docker SDK dependency is available). The container is launched detached and kept
alive by ``sandbox/container-init.sh`` (which applies the egress firewall, drops
to UID 1001, then blocks). Each ``run_bash`` becomes a ``docker exec`` of an
unprivileged ``bash -lc`` — so the agent never holds root or ``CAP_NET_ADMIN``.

Security posture enforced at launch (mirrors docs/THREAT_MODEL.md):
  - runtime from settings: ``runsc`` (gVisor) in prod, ``runc`` in dev_mode. If
    the configured runtime is not registered with Docker we raise
    ``SandboxStartError`` (the config gate already forbids non-runsc in prod).
  - ``--cap-drop=ALL`` then ``--cap-add=NET_ADMIN`` (only so container-init can
    install the egress firewall before dropping privileges).
  - ``--security-opt=no-new-privileges`` and the bundled seccomp profile.
  - ``--memory`` / ``--pids-limit`` / ``--cpus`` resource caps.
  - workspace bind-mount at ``/workspace`` (RW by default, RO optional).
  - egress allowlist passed via ``SKOLL_SANDBOX_NETWORK_ALLOWLIST`` and enforced
    inside the container by iptables (default DROP).
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

import structlog

from skoll.config import get_settings
from skoll.errors import SandboxStartError, SandboxTimeoutError

if TYPE_CHECKING:
    from skoll.config import SandboxSettings

log = structlog.get_logger(__name__)

# Path inside the container where the workspace is bind-mounted.
_WORKSPACE_MOUNT: Final[str] = "/workspace"

# Hard ceiling on captured output per stream, so a runaway command cannot
# exhaust backend memory. Bytes are decoded leniently for the result strings.
_MAX_OUTPUT_BYTES: Final[int] = 4 * 1024 * 1024

# Grace period (seconds) between SIGTERM and SIGKILL when a command times out.
_KILL_GRACE_SECONDS: Final[float] = 5.0

# Seconds allowed for non-exec docker control commands (run/rm/inspect).
_CONTROL_TIMEOUT_SECONDS: Final[float] = 30.0

# Unprivileged user (uid 1001) created in the image. `docker exec` must target it
# explicitly: container-init only drops PID 1 to this user (via gosu), so an exec
# without --user would otherwise run agent workloads as root.
_SANDBOX_USER: Final[str] = "skoll"


@dataclass
class BashResult:
    """Outcome of a single command executed in the sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


@dataclass
class ExecResult:
    """Lower-level ``exec`` outcome: ``(stdout, stderr, exit_code)`` plus timing."""

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool


def _decode(raw: bytes) -> str:
    """Decode subprocess bytes leniently (command output may not be UTF-8)."""
    if len(raw) > _MAX_OUTPUT_BYTES:
        raw = raw[:_MAX_OUTPUT_BYTES]
    return raw.decode("utf-8", errors="replace")


class SandboxSession:
    """Host-side controller for one agent session's sandbox container.

    Construct via :meth:`start` (it launches the container). Use :meth:`exec` for
    raw argv execution or :meth:`run_bash` for the shell-tool convenience wrapper,
    and :meth:`stop` / :meth:`shutdown` to tear the container down.
    """

    # docker binary resolved once; overridable in tests.
    _docker_bin: ClassVar[str] = "docker"

    def __init__(
        self,
        *,
        session_id: str,
        container_name: str,
        workspace_root: Path,
        settings: SandboxSettings,
    ) -> None:
        self.session_id = session_id
        self.container_name = container_name
        self.workspace_root = workspace_root
        self._settings = settings
        self._lock = asyncio.Lock()
        self._stopped = False

    # ------------------------------------------------------------------ start

    @classmethod
    async def start(
        cls,
        *,
        session_id: str,
        workspace_root: str | Path,
        read_only_workspace: bool = False,
    ) -> SandboxSession:
        """Launch the container, apply the network policy, return a ready session.

        Raises:
            SandboxStartError: docker missing, runtime not registered, the
                workspace path is invalid, or ``docker run`` fails.
        """
        settings = get_settings().sandbox
        docker = cls._resolve_docker_bin()

        ws = Path(workspace_root).expanduser().resolve()
        if not ws.is_dir():
            raise SandboxStartError(
                f"workspace_root {str(ws)!r} does not exist or is not a directory"
            )

        await cls._ensure_runtime_available(docker, settings.runtime)

        container_name = f"skoll-sbx-{session_id}"
        # Defensive: remove any stale container with the same name (best effort).
        await cls._force_remove(docker, container_name)

        mount_mode = "ro" if read_only_workspace else "rw"
        argv = cls._build_run_argv(
            docker=docker,
            settings=settings,
            container_name=container_name,
            workspace=ws,
            mount_mode=mount_mode,
        )

        log.info(
            "sandbox.start",
            session_id=session_id,
            container=container_name,
            runtime=settings.runtime,
            mount_mode=mount_mode,
            memory_mb=settings.memory_mb,
        )

        rc, out, err = await cls._run_control(argv, timeout=_CONTROL_TIMEOUT_SECONDS)
        if rc != 0:
            raise SandboxStartError(
                f"failed to launch sandbox container (exit {rc}): {err.strip() or out.strip()}"
            )

        session = cls(
            session_id=session_id,
            container_name=container_name,
            workspace_root=ws,
            settings=settings,
        )

        # Confirm the container is actually running (catches an init-script abort,
        # e.g. the firewall could not be installed → container-init exits non-zero).
        if not await session._is_running():
            logs = await session._collect_logs()
            await cls._force_remove(docker, container_name)
            raise SandboxStartError(
                f"sandbox container exited immediately after launch. Container logs:\n{logs}"
            )
        return session

    # ------------------------------------------------------------------- exec

    async def exec(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        working_directory: str = ".",
    ) -> ExecResult:
        """Run ``argv`` inside the container, returning stdout/stderr/exit code.

        ``argv`` is passed list-form to ``docker exec`` — it is NOT shell-parsed by
        the host. ``working_directory`` is resolved relative to ``/workspace``.

        Raises:
            SandboxStartError: the session has been stopped.
            SandboxTimeoutError: the command exceeded ``timeout`` and was killed.
        """
        if self._stopped:
            raise SandboxStartError("sandbox session has been stopped")
        if not argv:
            raise SandboxStartError("exec requires a non-empty argv")

        effective_timeout = (
            timeout if timeout is not None else float(self._settings.bash_timeout_seconds)
        )
        workdir = self._container_workdir(working_directory)

        exec_argv = [
            self._docker_bin,
            "exec",
            "--user",
            _SANDBOX_USER,
            "--workdir",
            workdir,
            self.container_name,
            *argv,
        ]

        # Serialize: one command at a time per session (matches entrypoint.py
        # protocol contract and avoids interleaved docker-exec state).
        async with self._lock:
            return await self._exec_once(exec_argv, effective_timeout)

    async def _exec_once(self, exec_argv: list[str], timeout: float) -> ExecResult:
        loop = asyncio.get_running_loop()
        start = loop.time()
        proc = await asyncio.create_subprocess_exec(
            *exec_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            stdout_b, stderr_b = await self._terminate(proc)
        duration_ms = int((loop.time() - start) * 1000)

        if timed_out:
            # Mirror the timeout into a typed error so callers can branch on it,
            # while still surfacing whatever partial output we captured.
            raise SandboxTimeoutError(
                f"command timed out after {timeout:.0f}s in sandbox {self.container_name}"
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        return ExecResult(
            stdout=_decode(stdout_b),
            stderr=_decode(stderr_b),
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=False,
        )

    async def _terminate(self, proc: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
        """SIGTERM the docker-exec client, then SIGKILL after a grace period.

        Killing the local ``docker exec`` client does not by itself stop the
        in-container process, so we also issue ``docker exec ... kill`` is avoided
        (no reliable pid); instead the container's own per-command supervision
        (Phase 2.4 entrypoint) and the overall ``stop()`` reclaim runaway work.
        For 1.10 the host-side timeout + client kill is the enforced boundary.
        """
        proc.terminate()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=_KILL_GRACE_SECONDS
            )
        except TimeoutError:
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()
        return stdout_b, stderr_b

    # --------------------------------------------------------------- run_bash

    async def run_bash(
        self,
        command: str,
        *,
        working_directory: str = ".",
        timeout_seconds: int | None = None,
    ) -> BashResult:
        """Run ``command`` under ``bash -lc`` in the sandbox (the ``run_bash`` tool).

        This is the entry point Phase 2.4's ``run_bash`` tool calls. The command
        string is executed by *bash inside the container* (where shell expansion is
        contained), never by a host shell.
        """
        timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(self._settings.bash_timeout_seconds)
        )
        try:
            result = await self.exec(
                ["bash", "-lc", command],
                timeout=timeout,
                working_directory=working_directory,
            )
        except SandboxTimeoutError:
            return BashResult(
                exit_code=124,  # conventional timeout exit code (coreutils `timeout`)
                stdout="",
                stderr=f"command timed out after {timeout:.0f}s",
                duration_ms=int(timeout * 1000),
                timed_out=True,
            )
        return BashResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=False,
        )

    # --------------------------------------------------------------- teardown

    async def stop(self) -> None:
        """Force-remove the container. Idempotent."""
        if self._stopped:
            return
        self._stopped = True
        log.info("sandbox.stop", session_id=self.session_id, container=self.container_name)
        await self._force_remove(self._docker_bin, self.container_name)

    async def shutdown(self) -> None:
        """Alias for :meth:`stop` (matches the session-lifecycle naming used elsewhere)."""
        await self.stop()

    # --------------------------------------------------------------- helpers

    @classmethod
    def _resolve_docker_bin(cls) -> str:
        found = shutil.which(cls._docker_bin)
        if found is None:
            raise SandboxStartError(
                "docker executable not found on PATH; the sandbox requires Docker"
            )
        return found

    @classmethod
    async def _ensure_runtime_available(cls, docker: str, runtime: str) -> None:
        """Verify ``runtime`` is registered with the Docker daemon."""
        rc, out, err = await cls._run_control(
            [docker, "info", "--format", "{{json .Runtimes}}"],
            timeout=_CONTROL_TIMEOUT_SECONDS,
        )
        if rc != 0:
            raise SandboxStartError(
                f"could not query docker runtimes (is the daemon running?): "
                f"{err.strip() or out.strip()}"
            )
        if runtime not in out:
            raise SandboxStartError(
                f"configured sandbox runtime {runtime!r} is not registered with Docker "
                f"(available: {out.strip()}). Install/enable it, or set "
                f"SKOLL_SANDBOX_RUNTIME to an available runtime (dev_mode required for non-runsc)."
            )

    @staticmethod
    def _build_run_argv(
        *,
        docker: str,
        settings: SandboxSettings,
        container_name: str,
        workspace: Path,
        mount_mode: str,
    ) -> list[str]:
        """Assemble the hardened ``docker run`` argv (list-form, no shell)."""
        seccomp = Path(__file__).resolve().parents[4] / "sandbox" / "seccomp.json"
        bind = f"type=bind,source={workspace},target={_WORKSPACE_MOUNT}"
        if mount_mode == "ro":
            bind += ",readonly"

        argv = [
            docker,
            "run",
            "--detach",
            "--name",
            container_name,
            "--runtime",
            settings.runtime,
            # Resource caps.
            "--memory",
            f"{settings.memory_mb}m",
            "--memory-swap",
            f"{settings.memory_mb}m",  # disable swap (== memory) so the cap is hard
            "--cpus",
            "1.0",
            "--pids-limit",
            "256",
            # Privilege hardening: drop everything, re-add only NET_ADMIN so the
            # init script can install the egress firewall before dropping to 1001.
            "--cap-drop",
            "ALL",
            "--cap-add",
            "NET_ADMIN",
            "--security-opt",
            "no-new-privileges",
            # Read-only root FS; writable scratch on tmpfs only.
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",  # nosec B108 docker --tmpfs mount target, not a host temp file
            "--tmpfs",
            "/run:rw,nosuid,nodev,size=16m",
            # Home needs to be writable for tooling (pip --user cache, git config).
            "--tmpfs",
            "/home/skoll:rw,nosuid,nodev,size=128m,uid=1001,gid=1001",
            # Egress allowlist consumed by container-init.sh / init-network.sh.
            "--env",
            f"SKOLL_SANDBOX_NETWORK_ALLOWLIST={settings.network_allowlist}",
            # Make the host reachable as host.docker.internal (LM Studio).
            "--add-host",
            "host.docker.internal:host-gateway",
            # Workspace bind mount.
            "--mount",
            bind,
        ]
        if seccomp.is_file():
            argv += ["--security-opt", f"seccomp={seccomp}"]
        argv.append(settings.image)
        return argv

    @classmethod
    async def _force_remove(cls, docker: str, container_name: str) -> None:
        await cls._run_control(
            [docker, "rm", "--force", container_name],
            timeout=_CONTROL_TIMEOUT_SECONDS,
        )

    async def _is_running(self) -> bool:
        rc, out, _ = await self._run_control(
            [
                self._docker_bin,
                "inspect",
                "--format",
                "{{.State.Running}}",
                self.container_name,
            ],
            timeout=_CONTROL_TIMEOUT_SECONDS,
        )
        return rc == 0 and out.strip() == "true"

    async def _collect_logs(self) -> str:
        _, out, err = await self._run_control(
            [self._docker_bin, "logs", self.container_name],
            timeout=_CONTROL_TIMEOUT_SECONDS,
        )
        return (out + err).strip()[:4096]

    @staticmethod
    async def _run_control(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
        """Run a short-lived docker control command; return (rc, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, "", f"control command timed out after {timeout:.0f}s: {argv[1:2]}"
        rc = proc.returncode if proc.returncode is not None else -1
        return rc, _decode(stdout_b), _decode(stderr_b)

    def _container_workdir(self, working_directory: str) -> str:
        """Resolve ``working_directory`` to an absolute path under ``/workspace``.

        Defends against escaping the mount via ``..`` — the resolved path must stay
        within ``/workspace``; otherwise we fall back to the mount root.
        """
        base = PurePosixWorkspace(_WORKSPACE_MOUNT)
        return base.resolve_within(working_directory)


class PurePosixWorkspace:
    """Tiny helper to resolve a relative subdir within the POSIX workspace mount.

    Kept separate (and POSIX-only) so resolution behaves identically regardless of
    the host OS — the container is always Linux even when the backend runs on
    Windows, so we must not use ``pathlib`` host semantics here.
    """

    def __init__(self, root: str) -> None:
        self._root = root.rstrip("/") or "/"

    def resolve_within(self, sub: str) -> str:
        sub = (sub or ".").strip()
        if sub.startswith("/"):
            candidate_parts = sub.split("/")
        else:
            candidate_parts = [*self._root.split("/"), *sub.split("/")]
        stack: list[str] = []
        for part in candidate_parts:
            if part in ("", "."):
                continue
            if part == "..":
                if stack:
                    stack.pop()
                continue
            stack.append(part)
        resolved = "/" + "/".join(stack)
        root = self._root
        if resolved == root or resolved.startswith(root + "/"):
            return resolved
        # Escaped the mount → clamp to the mount root.
        return root
