"""API route modules."""

from claimflow.api.routes.claims import router as claims_router
from claimflow.api.routes.health import router as health_router
from claimflow.api.routes.review import router as review_router
from claimflow.api.routes.uploads import router as uploads_router

__all__ = ["claims_router", "health_router", "uploads_router", "review_router"]
