"""Health-check endpoints."""

from fastapi import APIRouter

from claimflow import __version__
from claimflow.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return service liveness and version metadata."""
    settings = get_settings()
    return {
        "status": "ok",
        "project": settings.project_name,
        "version": __version__,
        "environment": settings.environment,
    }
