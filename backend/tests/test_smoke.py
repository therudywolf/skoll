"""Smoke tests for the implemented Phase-0 surface.

These exercise the parts of the skeleton that are real today (package metadata,
the FastAPI app factory, settings defaults, the error hierarchy) and lock in the
security-critical defaults. Stubbed modules are covered by their own phase Issues.
"""

from __future__ import annotations

import skoll
from skoll.app import create_app
from skoll.config import Settings
from skoll.errors import PathOutsideWorkspaceError, PreflightError, SkollError


def test_package_version() -> None:
    assert skoll.__version__ == "0.1.0a0"


def test_create_app_metadata() -> None:
    app = create_app()
    assert app.title == "Skoll Backend"
    assert app.version == "0.1.0a0"


def test_settings_defaults() -> None:
    s = Settings()
    assert s.port == 8000
    assert s.log_format == "json"
    # Sandbox must default to the gVisor runtime, never plain runc.
    assert s.sandbox.runtime == "runsc"


def test_security_defaults_are_safe() -> None:
    # Write/exec tools must NOT auto-approve by default (human-in-the-loop gate).
    agent = Settings().agent
    assert agent.auto_approve_write_tools is False
    assert agent.auto_approve_exec_tools is False
    # Read-only tools may auto-approve.
    assert agent.auto_approve_read_tools is True


def test_error_hierarchy_and_codes() -> None:
    assert issubclass(PathOutsideWorkspaceError, PreflightError)
    assert issubclass(PreflightError, SkollError)
    assert PathOutsideWorkspaceError().code == "preflight.path_outside_workspace"
