"""structlog configuration.

Issue: phase-0.6.

Two output modes, chosen by ``settings.log_format``:
  - ``json``    → machine-readable JSON lines (production / file logs)
  - ``console`` → coloured, human-readable (local dev)

Every HTTP-originated log line carries a ``request_id`` (a UUID bound per request by the
middleware in ``skoll.app``). We use structlog's ``contextvars`` integration so the id is
attached to *every* log call made while handling a request, without threading it through
function signatures.

No telemetry, no remote logging — local stdout/files only (AGENTS.md §3.8).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
)

if TYPE_CHECKING:
    from skoll.config import Settings

# The context key under which the per-request id is bound.
REQUEST_ID_KEY = "request_id"

_configured = False


def configure_logging(settings: Settings) -> None:
    """Configure structlog process-wide. Idempotent.

    Wires the stdlib ``logging`` root to the requested level and installs the structlog
    processor chain. ``contextvars`` merging is first in the chain so bound request ids
    appear on every event.
    """
    global _configured

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def new_request_id() -> str:
    """Generate a fresh request id (UUID4 hex-with-dashes string)."""
    return str(uuid.uuid4())


def bind_request_id(request_id: str) -> None:
    """Bind ``request_id`` into the structlog contextvars for the current task.

    Call at the start of request handling; pair with :func:`clear_request_context` in a
    ``finally`` so the binding does not leak to the next request reusing the worker.
    """
    bind_contextvars(**{REQUEST_ID_KEY: request_id})


def clear_request_context() -> None:
    """Clear all contextvars bound for the current request."""
    clear_contextvars()
