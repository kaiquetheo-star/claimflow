"""Prometheus metrics exposition endpoint."""

from fastapi import APIRouter, Response

from claimflow.core.metrics import metrics

router = APIRouter(tags=["observability"])


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=Response,
)
async def prometheus_metrics() -> Response:
    """Expose claim-processing counters in Prometheus text format."""
    return Response(
        content=metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
