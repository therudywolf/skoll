"""Tests for skoll.config._validate_production_safety (Issue 0.6).

This is the production-safety gate: the backend must refuse to start in unsafe configs
unless dev_mode is explicitly on.
"""

from __future__ import annotations

import logging

import pytest
from skoll.config import Settings, _validate_production_safety
from skoll.errors import ConfigError


def test_runc_without_dev_mode_raises() -> None:
    s = Settings()
    s.sandbox.runtime = "runc"
    s.dev_mode = False
    with pytest.raises(ConfigError):
        _validate_production_safety(s)


def test_runc_with_dev_mode_passes() -> None:
    s = Settings()
    s.sandbox.runtime = "runc"
    s.dev_mode = True
    # Should not raise.
    _validate_production_safety(s)


def test_kata_without_dev_mode_raises() -> None:
    s = Settings()
    s.sandbox.runtime = "kata"
    s.dev_mode = False
    with pytest.raises(ConfigError):
        _validate_production_safety(s)


def test_default_settings_pass() -> None:
    # Defaults are safe (runsc, localhost LM Studio, exec auto-approve off).
    _validate_production_safety(Settings())


def test_remote_lmstudio_without_dev_mode_raises() -> None:
    s = Settings()
    s.lmstudio.base_url = "http://192.168.1.50:1234"
    s.dev_mode = False
    with pytest.raises(ConfigError):
        _validate_production_safety(s)


def test_remote_lmstudio_with_dev_mode_passes() -> None:
    s = Settings()
    s.lmstudio.base_url = "http://192.168.1.50:1234"
    s.dev_mode = True
    _validate_production_safety(s)


def test_localhost_variants_pass() -> None:
    for url in (
        "http://127.0.0.1:1234",
        "http://localhost:1234",
        "http://host.docker.internal:1234",
        "http://[::1]:1234",
    ):
        s = Settings()
        s.lmstudio.base_url = url
        s.dev_mode = False
        _validate_production_safety(s)  # must not raise


def test_auto_approve_exec_without_dev_mode_warns_but_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    s = Settings()
    s.agent.auto_approve_exec_tools = True
    s.dev_mode = False
    with caplog.at_level(logging.WARNING):
        # Must NOT raise — just a loud warning.
        _validate_production_safety(s)
