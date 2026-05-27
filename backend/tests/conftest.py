"""Shared pytest fixtures.

LM Studio is NEVER hit in unit tests. Integration tests are marked @pytest.mark.integration
and skipped in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def lm_studio_traces_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "lm_studio"


# TODO(phase-0.3): fixture for mocked LMStudioClient backed by respx
# TODO(phase-1.1): fixture that replays captured SSE traces
