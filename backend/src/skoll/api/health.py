"""GET /api/health.

Issue: phase-0.2.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from skoll import __version__
from skoll.config import get_settings
from skoll.lm.client import LMStudioClient

logger = structlog.get_logger(__name__)

router = APIRouter()

# Hard cap on how long the LM Studio reachability probe may take. A hung LM Studio must
# never block the health endpoint (Issue 0.2 security note).
_PROBE_TIMEOUT_SECONDS = 1.0


class HealthStatus(BaseModel):
    """Response model — matches contracts/openapi.yaml#/components/schemas/HealthStatus."""

    status: str
    version: str
    lm_studio_reachable: bool


async def _probe_lm_studio() -> bool:
    """Return True iff LM Studio answers ``list_models`` within the probe timeout.

    Any failure — connection refused, timeout, auth error, malformed response — yields
    False. We build a short-lived client whose own timeout is 1s so even a half-open
    socket cannot wedge the endpoint, and we wrap the whole call in asyncio.wait_for as a
    belt-and-braces second deadline.
    """
    settings = get_settings()
    client = LMStudioClient(
        base_url=settings.lmstudio.base_url,
        api_key=settings.lmstudio.api_key,
        api_mode=settings.lmstudio.api_mode,
        timeout_seconds=1,
    )
    try:
        await asyncio.wait_for(client.list_models(), timeout=_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        # Any failure (timeout, refused, auth, bad JSON) → not reachable. We deliberately
        # catch broadly: the health probe must never raise. CancelledError is a
        # BaseException and is intentionally NOT swallowed (client disconnect).
        logger.debug("health.lm_probe_failed", error=str(exc))
        return False
    else:
        return True
    finally:
        await client.aclose()


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    """Return liveness + LM Studio reachability.

    Implementation: see contracts/openapi.yaml → HealthStatus.
    Probe LM Studio with a 1s timeout; set lm_studio_reachable=False on any failure.
    """
    reachable = await _probe_lm_studio()
    return HealthStatus(
        status="ok",
        version=__version__,
        lm_studio_reachable=reachable,
    )
