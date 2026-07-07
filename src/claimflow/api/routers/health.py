"""Backward-compatible re-export — prefer ``claimflow.api.routes.health``."""

from claimflow.api.routes.health import router

__all__ = ["router"]
