"""PostgreSQL claim persistence — claims survive engine/store restart."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from claimflow.agents.states import ClaimStatus
from claimflow.core.config import Settings, get_settings
from claimflow.db.session import Database
from claimflow.services.claim_store import ClaimStore

_TEST_PG_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://claimflow:claimflow@localhost:5432/claimflow",
)


def _build_settings(url: str) -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        database_url=url,
        checkpoint_database_url=url,
        storage_backend="local",
        local_upload_dir="./test_uploads_pg",
        use_mock_llm=True,
    )


def _run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    get_settings.cache_clear()


@pytest.fixture
def postgres_ready() -> str:
    """Ensure Postgres is reachable and schema is migrated; otherwise skip.

    Sync fixture so Alembic can call ``asyncio.run`` without nesting event loops.
    """
    settings = _build_settings(_TEST_PG_URL)

    async def _probe() -> None:
        db = Database()
        try:
            await db.startup(settings)
            async with db.session() as session:
                await session.connection()
        finally:
            await db.shutdown()

    try:
        asyncio.run(_probe())
    except (OperationalError, OSError, ConnectionRefusedError) as exc:
        pytest.skip(f"PostgreSQL unavailable at {_TEST_PG_URL}: {exc}")

    _run_migrations(_TEST_PG_URL)
    return _TEST_PG_URL


@pytest.mark.asyncio
async def test_postgres_claim_survives_restart(postgres_ready: str) -> None:
    """Save a claim, tear down the engine, and reload it from a fresh store."""
    claim_id = f"CLM-PG-PERSIST-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    settings = _build_settings(postgres_ready)

    # --- Session 1: write ---
    db1 = Database()
    store1 = ClaimStore()
    await db1.startup(settings)
    await store1.startup(settings, db1)
    assert store1.backend == "postgres"

    payload = {
        "claim_id": claim_id,
        "fraud_risk_score": 0.77,
        "extracted_data": {"cliente_nome": "Persistência", "tipo_dano": "AGUA"},
        "awaiting_human_decision": True,
    }
    await store1.save_result(claim_id, ClaimStatus.HUMAN_REVIEW, payload)
    await store1.shutdown()
    await db1.shutdown()

    # --- Session 2: new engine/store ("restart") ---
    db2 = Database()
    store2 = ClaimStore()
    await db2.startup(settings)
    await store2.startup(settings, db2)

    restored = await store2.get(claim_id)
    assert restored is not None
    assert restored.claim_id == claim_id
    assert restored.status == ClaimStatus.HUMAN_REVIEW
    assert restored.payload["fraud_risk_score"] == pytest.approx(0.77)
    assert restored.payload["extracted_data"]["cliente_nome"] == "Persistência"

    queue = await store2.list_human_review_queue()
    assert any(item.claim_id == claim_id for item in queue)

    await store2.shutdown()
    await db2.shutdown()
