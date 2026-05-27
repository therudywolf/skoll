"""GET /api/health.

Issue: phase-0.2.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    """Return liveness + LM Studio reachability.

    Implementation: see contracts/openapi.yaml → HealthStatus.
    Probe LM Studio with a 1s timeout; set lm_studio_reachable=False on any failure.
    """
    # TODO(phase-0.2)
    raise NotImplementedError
