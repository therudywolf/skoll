"""FastAPI application factory.

Implementation issue: phase-0.2 (skeleton + health), 0.4 (chat), 0.6 (CORS + structlog).

The factory pattern is used so tests can instantiate the app with custom
settings without touching globals.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from skoll.api import chat, health, sessions
from skoll.config import get_settings
from skoll.log import (
    bind_request_id,
    clear_request_context,
    configure_logging,
    new_request_id,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.middleware.base import RequestResponseEndpoint

logger = structlog.get_logger(__name__)

# Dev-only CORS origins. In production no browser origin is allowed (the SPA is served
# same-origin / behind a reverse proxy). See AGENTS.md §9 phase-0.
_DEV_CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Header carrying the per-request correlation id (echoed back to the client).
_REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a per-request id into structlog contextvars and log each request.

    Honours an inbound ``X-Request-ID`` (trusted only for log correlation, never for
    auth) or mints a fresh UUID. The id is cleared in ``finally`` so it never leaks to
    the next request handled by the same worker, and echoed in the response header.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or new_request_id()
        bind_request_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log the failure WITH the request id, then re-raise for the exception
            # handlers. Method/path only — never the body (may contain user code).
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "http.request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise
        else:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            response.headers[_REQUEST_ID_HEADER] = request_id
            return response
        finally:
            clear_request_context()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hook.

    Phase 0 keeps this minimal: configure logging, then log a non-fatal note about LM
    Studio reachability. DB / tool registry / RAG workers arrive in later phases.
    """
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "skoll.startup",
        version=app.version,
        log_format=settings.log_format,
        dev_mode=settings.dev_mode,
    )
    # Non-fatal LM Studio reachability note (does not block startup).
    try:
        from skoll.api.health import _probe_lm_studio

        reachable = await _probe_lm_studio()
    except Exception:  # pragma: no cover - defensive; probe already swallows failures
        reachable = False
    logger.info("skoll.lm_studio_probe", lm_studio_reachable=reachable)
    yield
    logger.info("skoll.shutdown")


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

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])

    # Middleware is applied bottom-up: the LAST added runs OUTERMOST. We want the
    # request-id binding to wrap everything (so even CORS-rejected requests are logged
    # with an id), hence CORS is added first and RequestContextMiddleware last.

    # CORS: dev origins only. Credentials disabled — we use no cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", _REQUEST_ID_HEADER],
    )

    app.add_middleware(RequestContextMiddleware)

    return app


# uvicorn entrypoint: `uv run uvicorn skoll.app:app`
app = create_app()
