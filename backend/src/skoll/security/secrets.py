"""Gitleaks-style secret scrubbing.

Issue: phase-1.12.

Reads patterns from .gitleaks.toml and replaces matches with `[REDACTED:<rule_id>]`.
This runs BEFORE content is fed to the LLM. Defense in depth: even if the LLM cooperates
with a prompt injection, the actual secret is already gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from re import Pattern


@dataclass(frozen=True)
class SecretMatch:
    rule_id: str
    start: int
    end: int


class SecretScrubber:
    """Compiled regex bank from .gitleaks.toml."""

    def __init__(self, patterns: dict[str, Pattern[str]]) -> None:
        self._patterns = patterns

    @classmethod
    def from_gitleaks_toml(cls, path: str) -> SecretScrubber:
        # TODO(phase-1.12)
        raise NotImplementedError

    def scrub(self, content: str) -> tuple[str, list[SecretMatch]]:
        """Return (scrubbed_content, list_of_matches)."""
        # TODO(phase-1.12)
        raise NotImplementedError
