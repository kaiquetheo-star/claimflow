"""FastAPI dependency helpers."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status
from langgraph.graph.state import CompiledStateGraph

from claimflow.core.config import get_settings
from claimflow.services.claim_store import ClaimStore


def get_claim_graph(request: Request) -> CompiledStateGraph:
    """Return the compiled LangGraph instance from application state."""
    graph = getattr(request.app.state, "claim_graph", None)
    if graph is None:
        msg = "Claim graph is not initialised"
        raise RuntimeError(msg)
    return graph


def get_claim_store(request: Request) -> ClaimStore:
    """Return the claim store from application state."""
    store = getattr(request.app.state, "claim_store", None)
    if store is None:
        msg = "Claim store is not initialised"
        raise RuntimeError(msg)
    return store


def require_api_key(
    x_api_key: str | None = Header(
        default=None,
        alias="X-API-Key",
        description="Shared application API key.",
    ),
) -> str:
    """Validate the ``X-API-Key`` header against ``Settings.api_key``.

    Applied to mutating endpoints (`POST /claims/submit`, `POST /uploads`,
    `POST /review/{id}/decision`). ``GET /health`` stays public.
    """
    expected = get_settings().api_key.get_secret_value()
    if not x_api_key or not _constant_time_equals(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide a valid X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key


# Alias used by some route type hints / docs.
get_api_key = require_api_key


def _constant_time_equals(provided: str, expected: str) -> bool:
    """Compare secrets in constant time; unequal lengths never match."""
    provided_bytes = provided.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if len(provided_bytes) != len(expected_bytes):
        return False
    return secrets.compare_digest(provided_bytes, expected_bytes)
