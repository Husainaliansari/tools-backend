"""Health check endpoint.

Exposes a single, dependency-free liveness endpoint used by load balancers,
orchestrators, and uptime monitors. It intentionally performs no downstream
checks so it always reflects *process* liveness cheaply.
"""

from __future__ import annotations

from fastapi import APIRouter, status

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness health check",
    response_description="Service is healthy.",
)
async def health() -> dict[str, str]:
    """Return the service liveness status."""
    return {"status": "healthy"}
