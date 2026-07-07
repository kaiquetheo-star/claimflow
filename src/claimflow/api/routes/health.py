"""Health-check endpoints with Alibaba Cloud service verification."""

from fastapi import APIRouter

from claimflow import __version__
from claimflow.core.config import get_settings
from claimflow.services.alibaba_cloud_integration import verify_alibaba_cloud_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, object]:
    """Return service health including Alibaba Cloud integration status.

    Used for operational monitoring and hackathon proof — demonstrates live
    connectivity to DashScope (Qwen Cloud), OSS, and RAM-configured credentials.
    """
    settings = get_settings()
    alibaba_status = await verify_alibaba_cloud_connection(settings)

    return {
        "status": alibaba_status["status"],
        "project": settings.project_name,
        "version": __version__,
        "environment": settings.environment,
        "alibaba_cloud_services": alibaba_status["alibaba_cloud_services"],
    }
