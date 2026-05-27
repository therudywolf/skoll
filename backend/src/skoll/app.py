"""FastAPI application factory.

Implementation issue: phase-0.2 (backend skeleton with health endpoint).

The factory pattern is used so tests can instantiate the app with custom
settings without touching globals.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Startup/shutdown hook.

    Startup:
      - load `contracts/tools/*.json` into the tool registry
      - open SQLite connection
      - probe LM Studio reachability (non-fatal warning if unreachable)
      - launch background workers (RAG indexer)

    Shutdown:
      - flush pending writes
      - close DB
      - terminate any sandbox containers spawned by this process
    """
    # TODO(phase-0.2): wire up startup
    yield
    # TODO(phase-0.2): wire up shutdown


def create_app() -> FastAPI:
    """Build the FastAPI app.

    Order of router inclusion matters for OpenAPI tag grouping.
    """
    app = FastAPI(
        title="Skoll Backend",
        version="0.1.0a0",
        lifespan=lifespan,
        # Hide /docs in prod; explicit override via settings if needed.
        docs_url="/docs",
        redoc_url=None,
    )

    # TODO(phase-0.2): include routers
    #   from skoll.api import health, sessions, chat, files, tools
    #   app.include_router(health.router, prefix="/api", tags=["health"])
    #   app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    #   app.include_router(chat.router, prefix="/api", tags=["chat"])
    #   app.include_router(files.router, prefix="/api", tags=["files"])
    #   app.include_router(tools.router, prefix="/api", tags=["tools"])

    # TODO(phase-0.6): CORS, structlog middleware, exception handlers

    return app


# uvicorn entrypoint: `uv run uvicorn skoll.app:app`
app = create_app()
