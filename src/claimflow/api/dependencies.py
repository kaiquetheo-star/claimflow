"""FastAPI dependency helpers."""

from fastapi import Request
from langgraph.graph.state import CompiledStateGraph

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
