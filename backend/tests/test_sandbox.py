"""Tests for the sandbox controller (skoll.sandbox.session).

Unit tests (no Docker) cover the pure helpers + the hardened ``docker run`` argv.
Docker-backed tests are marked ``integration`` (skipped in CI; run locally with a
built ``skoll/sandbox:dev`` image — they force ``SKOLL_SANDBOX_RUNTIME=runc`` since
gVisor/runsc may not be registered on the dev host).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import skoll.config as cfg
from skoll.config import SandboxSettings, get_settings
from skoll.errors import SandboxStartError
from skoll.sandbox.session import (
    _MAX_OUTPUT_BYTES,
    PurePosixWorkspace,
    SandboxSession,
    _decode,
)


class TestPurePosixWorkspace:
    def test_root_and_simple_subdir(self) -> None:
        ws = PurePosixWorkspace("/workspace")
        assert ws.resolve_within(".") == "/workspace"
        assert ws.resolve_within("") == "/workspace"
        assert ws.resolve_within("src/auth.py") == "/workspace/src/auth.py"

    def test_parent_traversal_is_clamped(self) -> None:
        ws = PurePosixWorkspace("/workspace")
        assert ws.resolve_within("../../etc/passwd") == "/workspace"
        assert ws.resolve_within("a/../../b") == "/workspace"

    def test_absolute_outside_is_clamped(self) -> None:
        assert PurePosixWorkspace("/workspace").resolve_within("/etc/passwd") == "/workspace"

    def test_absolute_inside_is_kept(self) -> None:
        assert PurePosixWorkspace("/workspace").resolve_within("/workspace/src") == "/workspace/src"


def test_decode_truncates_and_is_lenient() -> None:
    out = _decode(b"x" * (_MAX_OUTPUT_BYTES + 100))
    assert len(out) == _MAX_OUTPUT_BYTES
    # invalid utf-8 bytes are replaced, never raise
    assert _decode(b"\xff\xfe ok").endswith("ok")


def test_build_run_argv_is_hardened() -> None:
    settings = SandboxSettings()  # defaults: runtime=runsc, image=skoll/sandbox:dev
    argv = SandboxSession._build_run_argv(
        docker="docker",
        settings=settings,
        container_name="skoll-sbx-test",
        workspace=Path("/ws"),
        mount_mode="rw",
    )
    assert "--runtime" in argv
    assert settings.runtime in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--cap-add") + 1] == "NET_ADMIN"
    assert "no-new-privileges" in argv
    assert "--read-only" in argv
    assert "--memory" in argv
    assert "--pids-limit" in argv
    assert any(a.startswith("SKOLL_SANDBOX_NETWORK_ALLOWLIST=") for a in argv)
    assert any("target=/workspace" in a for a in argv)
    assert argv[-1] == settings.image  # image is the final positional arg


def test_build_run_argv_readonly_mount() -> None:
    argv = SandboxSession._build_run_argv(
        docker="docker",
        settings=SandboxSettings(),
        container_name="c",
        workspace=Path("/ws"),
        mount_mode="ro",
    )
    assert any("readonly" in a for a in argv)


def test_resolve_docker_bin_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skoll.sandbox.session.shutil.which", lambda _: None)
    with pytest.raises(SandboxStartError):
        SandboxSession._resolve_docker_bin()


# --------------------------------------------------------------------- integration
# Require Docker + a built `skoll/sandbox:dev` image; skipped in CI (`-m "not integration"`).


@pytest.fixture
def _runc_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKOLL_SANDBOX_RUNTIME", "runc")
    monkeypatch.setenv("SKOLL_DEV_MODE", "true")
    monkeypatch.setattr(cfg, "_settings", None)
    get_settings()  # rebuild the singleton from the patched env


@pytest.mark.integration
async def test_start_exec_runs_unprivileged(tmp_path: Path, _runc_settings: None) -> None:
    session = await SandboxSession.start(session_id="ut-exec", workspace_root=str(tmp_path))
    try:
        echo = await session.exec(["echo", "ok"])
        assert echo.exit_code == 0
        assert "ok" in echo.stdout
        whoami = await session.exec(["id", "-un"])
        assert "skoll" in whoami.stdout  # never root inside the sandbox
    finally:
        await session.stop()


@pytest.mark.integration
async def test_egress_is_blocked(tmp_path: Path, _runc_settings: None) -> None:
    session = await SandboxSession.start(session_id="ut-egress", workspace_root=str(tmp_path))
    try:
        # Deny-by-default egress: a non-allowlisted host must be unreachable.
        result = await session.run_bash("curl -sS --max-time 5 https://example.com")
        assert result.exit_code != 0
    finally:
        await session.stop()
