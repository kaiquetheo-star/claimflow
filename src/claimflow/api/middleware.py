"""HTTP middleware for request IDs and observability headers."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from claimflow.core.context import (
    get_correlation_id,
    set_correlation_id,
    set_request_id,
)
from claimflow.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a unique request ID to every API call and echo it in the response.

    Also accepts an optional inbound ``X-Correlation-ID`` (or uses the request ID)
    so a claim can be traced across services. Claim handlers may overwrite the
    correlation ID with the ``claim_id``.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        set_request_id(request_id)
        set_correlation_id(correlation_id)

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled exception during request",
                extra={"path": request.url.path, "method": request.method},
            )
            set_request_id(None)
            set_correlation_id(None)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = get_correlation_id() or correlation_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        logger.info(
            "HTTP request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        set_request_id(None)
        set_correlation_id(None)
        return response
