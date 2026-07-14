"""Request-scoped observability context (request ID + claim correlation ID)."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_request_id() -> str | None:
    return request_id_var.get()


def get_correlation_id() -> str | None:
    return correlation_id_var.get()


def set_request_id(value: str | None) -> None:
    request_id_var.set(value)


def set_correlation_id(value: str | None) -> None:
    correlation_id_var.set(value)


def bind_claim_correlation(claim_id: str) -> None:
    """Use the claim ID as the correlation ID for end-to-end claim tracing."""
    set_correlation_id(claim_id)
