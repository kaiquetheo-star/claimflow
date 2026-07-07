"""Claim snapshot persistence for the human-review dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from claimflow.agents.states import ClaimStatus
from claimflow.db.models import ClaimRecord
from claimflow.db.session import Database


@dataclass
class ClaimSnapshot:
    """Domain object returned by claim store queries."""

    claim_id: str
    status: ClaimStatus
    payload: dict[str, Any]
    reviewer_note: str | None
    created_at: datetime
    updated_at: datetime


class InMemoryClaimStore:
    """Development fallback when PostgreSQL is not configured."""

    def __init__(self) -> None:
        self._records: dict[str, ClaimSnapshot] = {}

    async def upsert(
        self,
        claim_id: str,
        status: ClaimStatus,
        payload: dict[str, Any],
    ) -> ClaimSnapshot:
        now = datetime.now(UTC)
        existing = self._records.get(claim_id)
        snapshot = ClaimSnapshot(
            claim_id=claim_id,
            status=status,
            payload=payload,
            reviewer_note=existing.reviewer_note if existing else None,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._records[claim_id] = snapshot
        return snapshot

    async def get(self, claim_id: str) -> ClaimSnapshot | None:
        return self._records.get(claim_id)

    async def list_by_status(
        self,
        status: ClaimStatus,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClaimSnapshot]:
        items = [r for r in self._records.values() if r.status == status]
        items.sort(key=lambda r: r.updated_at, reverse=True)
        return items[offset : offset + limit]

    async def apply_decision(
        self,
        claim_id: str,
        status: ClaimStatus,
        reviewer_note: str | None,
        analyst_id: str | None = None,
    ) -> ClaimSnapshot | None:
        record = self._records.get(claim_id)
        if record is None:
            return None
        now = datetime.now(UTC)
        payload = {
            **record.payload,
            "human_decision": {
                "analyst_id": analyst_id or "unknown",
                "decision": status.value,
                "analyst_notes": reviewer_note,
                "recorded_at": now.isoformat(),
            },
        }
        updated = ClaimSnapshot(
            claim_id=claim_id,
            status=status,
            payload=payload,
            reviewer_note=reviewer_note,
            created_at=record.created_at,
            updated_at=now,
        )
        self._records[claim_id] = updated
        return updated


class PostgresClaimStore:
    """PostgreSQL-backed claim snapshot store."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def _to_snapshot(self, record: ClaimRecord) -> ClaimSnapshot:
        return ClaimSnapshot(
            claim_id=record.claim_id,
            status=ClaimStatus(record.status),
            payload=record.payload,
            reviewer_note=record.reviewer_note,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def upsert(
        self,
        claim_id: str,
        status: ClaimStatus,
        payload: dict[str, Any],
    ) -> ClaimSnapshot:
        async with self._database.session() as session:
            record = await session.get(ClaimRecord, claim_id)
            if record is None:
                record = ClaimRecord(claim_id=claim_id, status=status, payload=payload)
                session.add(record)
            else:
                record.status = status
                record.payload = payload
                record.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(record)
            return self._to_snapshot(record)

    async def get(self, claim_id: str) -> ClaimSnapshot | None:
        async with self._database.session() as session:
            record = await session.get(ClaimRecord, claim_id)
            return self._to_snapshot(record) if record else None

    async def list_by_status(
        self,
        status: ClaimStatus,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClaimSnapshot]:
        async with self._database.session() as session:
            stmt = (
                select(ClaimRecord)
                .where(ClaimRecord.status == status)
                .order_by(ClaimRecord.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._to_snapshot(row) for row in result.scalars().all()]

    async def apply_decision(
        self,
        claim_id: str,
        status: ClaimStatus,
        reviewer_note: str | None,
        analyst_id: str | None = None,
    ) -> ClaimSnapshot | None:
        async with self._database.session() as session:
            record = await session.get(ClaimRecord, claim_id)
            if record is None:
                return None
            now = datetime.now(UTC)
            payload = {
                **record.payload,
                "human_decision": {
                    "analyst_id": analyst_id or "unknown",
                    "decision": status.value,
                    "analyst_notes": reviewer_note,
                    "recorded_at": now.isoformat(),
                },
            }
            record.status = status.value
            record.payload = payload
            record.reviewer_note = reviewer_note
            record.updated_at = now
            await session.commit()
            await session.refresh(record)
            return self._to_snapshot(record)
