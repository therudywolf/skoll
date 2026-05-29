"""Settings loaded from environment / .env.

Implementation issue: phase-0.6.

All env vars are prefixed `SKOLL_`. See .env.example for the full list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LMStudioSettings(BaseSettings):
    base_url: str = "http://127.0.0.1:1234"
    api_key: str = ""
    api_mode: Literal["native", "openai"] = "native"
    default_model: str = ""
    timeout_seconds: int = 600

    model_config = SettingsConfigDict(env_prefix="SKOLL_LMSTUDIO_")


class SandboxSettings(BaseSettings):
    image: str = "skoll/sandbox:dev"
    runtime: Literal["runsc", "runc", "kata"] = "runsc"
    bash_timeout_seconds: int = 30
    network_allowlist: str = "host.docker.internal:1234,r.jina.ai:443,searxng:8080"
    memory_mb: int = 512

    model_config = SettingsConfigDict(env_prefix="SKOLL_SANDBOX_")


class AgentSettings(BaseSettings):
    max_iterations: int = 20
    auto_approve_read_tools: bool = True
    auto_approve_write_tools: bool = False
    auto_approve_exec_tools: bool = False

    model_config = SettingsConfigDict(env_prefix="SKOLL_AGENT_")


class RAGSettings(BaseSettings):
    embedding_model: str = ""
    chunk_size_tokens: int = 1024
    chunk_overlap_tokens: int = 128
    faiss_index_path: Path = Path(".skoll_cache/faiss")

    model_config = SettingsConfigDict(env_prefix="SKOLL_RAG_")


class SearchSettings(BaseSettings):
    searxng_url: str = "http://localhost:8089"
    primary: Literal["searxng", "duckduckgo"] = "searxng"
    jina_reader_api_key: str = ""

    model_config = SettingsConfigDict(env_prefix="SKOLL_")  # SKOLL_SEARXNG_URL etc.


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    dev_mode: bool = False

    workspace_root: Path = Path("./workspaces")
    cache_dir: Path = Path("./.skoll_cache")
    db_path: Path = Path("./.skoll_cache/skoll.sqlite")

    lmstudio: LMStudioSettings = Field(default_factory=LMStudioSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)

    model_config = SettingsConfigDict(
        env_prefix="SKOLL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Lazy singleton — populated on first access.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _validate_production_safety(_settings)
    return _settings


# Hosts considered "local" for the production-safety gate. 0.0.0.0 is deliberately
# excluded — it is not a valid client target and would weaken the non-localhost check.
_LOCALHOST_HOSTS: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
)


def _host_is_local(base_url: str) -> bool:
    """True if the URL's host is a loopback / local-dev host."""
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    return host in _LOCALHOST_HOSTS


def _validate_production_safety(s: Settings) -> None:
    """Refuse to start in unsafe configurations unless dev_mode is true.

    Implementation: see Issue phase-0.6. This is THE production-safety gate.
      - non-gVisor sandbox runtime (runc/kata) without dev_mode  -> ConfigError
      - auto-approving exec tools without dev_mode               -> loud warning
      - non-localhost LM Studio base_url without dev_mode        -> ConfigError
    """
    import structlog

    from skoll.errors import ConfigError

    log = structlog.get_logger(__name__)

    if s.sandbox.runtime != "runsc" and not s.dev_mode:
        raise ConfigError(
            f"Sandbox runtime {s.sandbox.runtime!r} is unsafe in production; "
            "gVisor ('runsc') is required. Set SKOLL_DEV_MODE=true to override for local dev."
        )

    if s.agent.auto_approve_exec_tools and not s.dev_mode:
        log.warning(
            "config.unsafe.auto_approve_exec_tools",
            message=(
                "auto_approve_exec_tools is ENABLED without dev_mode — the agent can run "
                "commands with no human approval. This is strongly discouraged in production."
            ),
        )

    if not _host_is_local(s.lmstudio.base_url) and not s.dev_mode:
        raise ConfigError(
            "LM Studio base_url points at a non-localhost host "
            f"({s.lmstudio.base_url!r}); refusing to start. Set SKOLL_DEV_MODE=true to "
            "opt in to a remote LM Studio endpoint."
        )
