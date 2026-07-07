"""Application-level claim store facade."""

from __future__ import annotations

from typing import Any

from claimflow.agents.states import ClaimStatus
from claimflow.core.config import Settings
from claimflow.core.logging import get_logger
from claimflow.db.repository import ClaimSnapshot, InMemoryClaimStore, PostgresClaimStore
from claimflow.db.session import Database

logger = get_logger(__name__)


class ClaimStore:
    """Unified interface for persisting and querying claim snapshots."""

    def __init__(self) -> None:
        self._backend: InMemoryClaimStore | PostgresClaimStore | None = None
        self._backend_name = "none"

    @property
    def backend(self) -> str:
        return self._backend_name

    async def startup(self, settings: Settings, database: Database) -> None:
        if database.is_configured:
            self._backend = PostgresClaimStore(database)
            self._backend_name = "postgres"
        else:
            self._backend = InMemoryClaimStore()
            self._backend_name = "memory"
        logger.info("Claim store initialised", extra={"backend": self._backend_name})

    async def shutdown(self) -> None:
        self._backend = None

    def _require_backend(self) -> InMemoryClaimStore | PostgresClaimStore:
        if self._backend is None:
            msg = "ClaimStore has not been started"
            raise RuntimeError(msg)
        return self._backend

    async def save_result(
        self,
        claim_id: str,
        status: ClaimStatus,
        payload: dict[str, Any],
    ) -> ClaimSnapshot:
        return await self._require_backend().upsert(claim_id, status, payload)

    async def get(self, claim_id: str) -> ClaimSnapshot | None:
        return await self._require_backend().get(claim_id)

    async def list_human_review_queue(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClaimSnapshot]:
        return await self._require_backend().list_by_status(
            ClaimStatus.HUMAN_REVIEW,
            limit=limit,
            offset=offset,
        )

    async def apply_decision(
        self,
        claim_id: str,
        status: ClaimStatus,
        reviewer_note: str | None,
        analyst_id: str | None = None,
    ) -> ClaimSnapshot | None:
        return await self._require_backend().apply_decision(
            claim_id,
            status,
            reviewer_note,
            analyst_id,
        )
