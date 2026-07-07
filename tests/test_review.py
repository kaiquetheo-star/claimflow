"""Tests for human-review API and claim store."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from claimflow.agents.states import ClaimStatus

_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
    "STORAGE_BACKEND": "local",
    "LOCAL_UPLOAD_DIR": "./test_uploads",
}


@pytest.fixture
def client() -> TestClient:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings
        from claimflow.tools.factory import reset_storage_client_cache

        get_settings.cache_clear()
        reset_storage_client_cache()

        from claimflow.api.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_storage_client_cache()


@pytest.mark.asyncio
async def test_claim_store_in_memory_roundtrip() -> None:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings
        from claimflow.db.session import Database
        from claimflow.services.claim_store import ClaimStore

        get_settings.cache_clear()
        settings = get_settings()
        database = Database()
        store = ClaimStore()
        await store.startup(settings, database)

        payload = {
            "claim_id": "CLM-REV-001",
            "status": ClaimStatus.HUMAN_REVIEW,
            "fraud_risk_score": 0.8,
            "extracted_data": {"cliente_nome": "João", "tipo_dano": "FOGO"},
        }
        await store.save_result("CLM-REV-001", ClaimStatus.HUMAN_REVIEW, payload)

        queue = await store.list_human_review_queue()
        assert len(queue) == 1
        assert queue[0].claim_id == "CLM-REV-001"

        updated = await store.apply_decision(
            "CLM-REV-001",
            ClaimStatus.APPROVED,
            "Documentação validada.",
        )
        assert updated is not None
        assert updated.status == ClaimStatus.APPROVED
        assert updated.reviewer_note == "Documentação validada."

        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_review_queue_endpoint(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-REV-002",
        ClaimStatus.HUMAN_REVIEW,
        {
            "fraud_risk_score": 0.75,
            "severity_score": 0.6,
            "extracted_data": {"cliente_nome": "Ana", "tipo_dano": "AGUA"},
        },
    )

    response = client.get("/api/v1/review/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["claim_id"] == "CLM-REV-002" for item in body["items"])


@pytest.mark.asyncio
async def test_review_decision_endpoint(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-REV-003",
        ClaimStatus.HUMAN_REVIEW,
        {"fraud_risk_score": 0.8},
    )

    response = client.post(
        "/api/v1/review/CLM-REV-003/decision",
        json={"decision": "REJECTED", "reviewer_note": "Fraude confirmada."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["reviewer_note"] == "Fraude confirmada."
    assert body["analyst_id"] == "demo-analyst"
    assert body["decided_at"] is not None


@pytest.mark.asyncio
async def test_review_decision_accepts_streamlit_payload(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-REV-004",
        ClaimStatus.APPROVED,
        {"fraud_risk_score": 0.2},
    )

    response = client.post(
        "/api/v1/review/CLM-REV-004/decision",
        json={
            "decision": "approved",
            "analyst_notes": "Payment authorized after review.",
            "analyst_id": "demo-analyst",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["reviewer_note"] == "Payment authorized after review."


@pytest.mark.asyncio
async def test_review_decision_rejects_duplicate(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-REV-005",
        ClaimStatus.HUMAN_REVIEW,
        {"fraud_risk_score": 0.8},
    )

    first = client.post(
        "/api/v1/review/CLM-REV-005/decision",
        json={"decision": "approved", "analyst_notes": "OK"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/review/CLM-REV-005/decision",
        json={"decision": "rejected", "analyst_notes": "Changed mind"},
    )
    assert second.status_code == 409
