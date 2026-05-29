"""Gitleaks-style secret scrubbing.

Issue: phase-1.12.

Reads patterns from .gitleaks.toml and replaces matches with `[REDACTED:<rule_id>]`.
This runs BEFORE content is fed to the LLM. Defense in depth: even if the LLM cooperates
with a prompt injection, the actual secret is already gone.

The repo's ``.gitleaks.toml`` declares a couple of project-specific ``[[rules]]`` and sets
``[extend].useDefault = true``. The upstream default ruleset is large and not vendored here,
so when ``useDefault`` is enabled we add a small, curated subset of the canonical gitleaks
default rules (matching their exact rule ids) covering the high-value credential shapes called
out in ``docs/THREAT_MODEL.md`` (AWS keys, JWTs, generic private keys). Rule ids match upstream
gitleaks so the redaction tag is recognisable.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from re import Pattern

# Curated subset of upstream gitleaks default rules, keyed by the canonical rule id.
# Only included when `.gitleaks.toml` sets `[extend].useDefault = true`.
# Source ids/regexes mirror gitleaks/config/gitleaks.toml.
_DEFAULT_RULES: dict[str, str] = {
    "aws-access-token": r"\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b",
    "jwt": (
        r"\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/\\_-]{17,}"
        r"\.(?:[a-zA-Z0-9/\\_-]{10,}={0,2})?)(['\"\s;]|\\[nr]|$)"
    ),
    "private-key": (
        r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY( BLOCK)?-----"
        r"[\s\S-]*?KEY( BLOCK)?-----"
    ),
    "github-pat": r"\bghp_[0-9a-zA-Z]{36}\b",
    "github-fine-grained-pat": r"\bgithub_pat_[0-9a-zA-Z_]{82}\b",
    "gitlab-pat": r"\bglpat-[0-9a-zA-Z_-]{20}\b",
    "slack-bot-token": r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9-]{24,}\b",
    "openai-api-key": r"\bsk-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20}\b",
}


@dataclass(frozen=True)
class SecretMatch:
    rule_id: str
    start: int
    end: int


def _compile(regex: str) -> Pattern[str]:
    # gitleaks rules are case-sensitive by default; compile verbatim.
    return re.compile(regex)


class SecretScrubber:
    """Compiled regex bank from .gitleaks.toml.

    Patterns are insertion-ordered: when two rules match overlapping spans, the rule that
    appears first wins (project-specific rules are loaded before the default subset).
    """

    def __init__(self, patterns: dict[str, Pattern[str]]) -> None:
        self._patterns = patterns

    @classmethod
    def from_gitleaks_toml(cls, path: str) -> SecretScrubber:
        """Build a scrubber from a gitleaks TOML config.

        Loads every ``[[rules]]`` entry (id + regex) and, if ``[extend].useDefault`` is true,
        appends the curated default subset for any id not already defined.
        """
        raw = Path(path).read_text(encoding="utf-8")
        data = tomllib.loads(raw)

        patterns: dict[str, Pattern[str]] = {}
        for rule in data.get("rules", []):
            rule_id = rule.get("id")
            regex = rule.get("regex")
            if not isinstance(rule_id, str) or not isinstance(regex, str):
                continue
            patterns[rule_id] = _compile(regex)

        extend = data.get("extend", {})
        if isinstance(extend, dict) and extend.get("useDefault") is True:
            for rule_id, regex in _DEFAULT_RULES.items():
                patterns.setdefault(rule_id, _compile(regex))

        return cls(patterns)

    def _matches(self, content: str) -> list[tuple[SecretMatch, int, int]]:
        """Collect non-overlapping match spans across all rules.

        Returns a list of ``(SecretMatch, redact_start, redact_end)`` where the redaction span
        is the rule's first capturing group when present (so trailing delimiters captured by the
        gitleaks regexes are preserved), else the whole match.
        """
        candidates: list[tuple[int, int, str]] = []
        for rule_id, pattern in self._patterns.items():
            for m in pattern.finditer(content):
                if m.lastindex:
                    redact_start, redact_end = m.start(1), m.end(1)
                else:
                    redact_start, redact_end = m.start(), m.end()
                if redact_end > redact_start:
                    candidates.append((redact_start, redact_end, rule_id))

        # Stable sort by start; longer spans first so the widest match wins on ties.
        candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))

        chosen: list[tuple[SecretMatch, int, int]] = []
        last_end = -1
        for start, end, rule_id in candidates:
            if start < last_end:
                continue  # overlaps an already-chosen span
            chosen.append((SecretMatch(rule_id=rule_id, start=start, end=end), start, end))
            last_end = end
        return chosen

    def scrub(self, content: str) -> tuple[str, list[SecretMatch]]:
        """Return (scrubbed_content, list_of_matches)."""
        matches = self._matches(content)
        if not matches:
            return content, []

        out: list[str] = []
        cursor = 0
        result_matches: list[SecretMatch] = []
        for match, start, end in matches:
            out.append(content[cursor:start])
            out.append(f"[REDACTED:{match.rule_id}]")
            cursor = end
            result_matches.append(match)
        out.append(content[cursor:])
        return "".join(out), result_matches


def _default_gitleaks_path() -> Path:
    """Locate the repo-root ``.gitleaks.toml``.

    Layout: ``<repo>/.gitleaks.toml`` with this module at
    ``<repo>/backend/src/skoll/security/secrets.py`` (parents[4] == repo root).
    """
    return Path(__file__).resolve().parents[4] / ".gitleaks.toml"


@lru_cache(maxsize=8)
def _scrubber_for(path: str) -> SecretScrubber:
    return SecretScrubber.from_gitleaks_toml(path)


def scrub(text: str, *, gitleaks_path: str | None = None) -> tuple[str, int]:
    """Scrub secrets from ``text`` using the repo's gitleaks rules.

    This is the convenience entry point used by every file/URL read path before the content
    reaches the LLM. Patterns are loaded once per config path and cached.

    Returns ``(scrubbed_text, redaction_count)``.
    """
    path = gitleaks_path if gitleaks_path is not None else str(_default_gitleaks_path())
    scrubber = _scrubber_for(path)
    scrubbed, matches = scrubber.scrub(text)
    return scrubbed, len(matches)
