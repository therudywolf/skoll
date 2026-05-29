"""Tests for gitleaks-style secret scrubbing (Issue 1.12).

The fake credentials below are syntactically valid for their detector but are not real keys.
Each is tagged ``# gitleaks:allow`` so the repo's own gitleaks scan does not flag this file.
"""

from __future__ import annotations

from pathlib import Path

from skoll.security.secrets import SecretScrubber, scrub

REPO_ROOT = Path(__file__).resolve().parents[2]
GITLEAKS_TOML = str(REPO_ROOT / ".gitleaks.toml")

# Canonical AWS example access key id (not a real credential).
FAKE_AWS = "AKIAIOSFODNN7EXAMPLE"  # gitleaks:allow
# Structurally valid JWT (header.payload.signature) with a dummy signature.
FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dummy-sig-aaaaaaaaaaaa"  # gitleaks:allow
)
# LM Studio token shape: sk-lm-<id>:<secret>.
FAKE_LM = "sk-lm-abcd1234:wxyz5678efgh"  # gitleaks:allow
# Jina AI key shape: jina_ + 40+ alphanumerics.
FAKE_JINA = "jina_abcdefghijklmnopqrstuvwxyz0123456789ABCD"  # gitleaks:allow


def _scrub(text: str) -> tuple[str, int]:
    return scrub(text, gitleaks_path=GITLEAKS_TOML)


def test_clean_text_unchanged() -> None:
    text = "def add(a: int, b: int) -> int:\n    return a + b\n"
    scrubbed, count = _scrub(text)
    assert scrubbed == text
    assert count == 0


def test_aws_key_redacted() -> None:
    scrubbed, count = _scrub(f"aws_key = {FAKE_AWS}")
    assert count == 1
    assert FAKE_AWS not in scrubbed
    assert "[REDACTED:aws-access-token]" in scrubbed


def test_jwt_redacted() -> None:
    scrubbed, count = _scrub(f"token: {FAKE_JWT}")
    assert count == 1
    assert FAKE_JWT not in scrubbed
    assert "[REDACTED:jwt]" in scrubbed


def test_lm_studio_token_redacted() -> None:
    scrubbed, count = _scrub(f"Authorization: Bearer {FAKE_LM}")
    assert count == 1
    assert FAKE_LM not in scrubbed
    assert "[REDACTED:lm-studio-token]" in scrubbed


def test_jina_key_redacted() -> None:
    scrubbed, count = _scrub(f"SKOLL_JINA_READER_API_KEY={FAKE_JINA}")
    assert count == 1
    assert FAKE_JINA not in scrubbed
    assert "[REDACTED:jina-api-key]" in scrubbed


def test_multiple_secrets_counted() -> None:
    text = f"a={FAKE_AWS}\nb={FAKE_LM}\nc={FAKE_JINA}"
    scrubbed, count = _scrub(text)
    assert count == 3
    for secret in (FAKE_AWS, FAKE_LM, FAKE_JINA):
        assert secret not in scrubbed
    assert "[REDACTED:aws-access-token]" in scrubbed
    assert "[REDACTED:lm-studio-token]" in scrubbed
    assert "[REDACTED:jina-api-key]" in scrubbed


def test_surrounding_text_preserved() -> None:
    scrubbed, _ = _scrub(f"prefix {FAKE_AWS} suffix")
    assert scrubbed == "prefix [REDACTED:aws-access-token] suffix"


def test_jwt_trailing_delimiter_preserved() -> None:
    # The gitleaks jwt regex captures a trailing delimiter; it must not be redacted away.
    scrubbed, count = _scrub(f'"{FAKE_JWT}";')
    assert count == 1
    assert scrubbed == '"[REDACTED:jwt]";'


def test_scrubber_class_returns_matches() -> None:
    scrubber = SecretScrubber.from_gitleaks_toml(GITLEAKS_TOML)
    scrubbed, matches = scrubber.scrub(f"key={FAKE_AWS}")
    assert len(matches) == 1
    assert matches[0].rule_id == "aws-access-token"
    assert scrubbed[matches[0].start : matches[0].start + len("[REDACTED:aws-access-token]")]
    assert FAKE_AWS not in scrubbed


def test_custom_rules_loaded_from_toml() -> None:
    # The project-specific rules from .gitleaks.toml must be present.
    scrubber = SecretScrubber.from_gitleaks_toml(GITLEAKS_TOML)
    assert "lm-studio-token" in scrubber._patterns
    assert "jina-api-key" in scrubber._patterns
    # And the default-subset rules are added because useDefault = true.
    assert "aws-access-token" in scrubber._patterns
    assert "jwt" in scrubber._patterns
