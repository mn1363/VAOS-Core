"""Health check endpoint used for liveness and readiness probes."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def get_health() -> dict[str, str]:
    """Report the API server's liveness status.

    Returns:
        A mapping containing the current status string.
    """
    return {"status": "ok"}
