"""Tests for human-review API and claim store."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.agents.states import ClaimStatus
from claimflow.core.config import Settings, get_settings

_TEST_API_KEY = "cf_hk_a8f3b2c19e4d5f60718293a4b5c6d7e8"
_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}


def _build_test_settings() -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        api_key=SecretStr(_TEST_API_KEY),
        storage_backend="local",
        local_upload_dir="./test_uploads",
        use_mock_llm=False,
    )


@pytest.fixture
def client() -> TestClient:
    test_settings = _build_test_settings()
    get_settings.cache_clear()

    with (
        patch("claimflow.core.config.get_settings", return_value=test_settings),
        patch("claimflow.api.dependencies.get_settings", return_value=test_settings),
        patch("claimflow.tools.factory.get_settings", return_value=test_settings),
        patch(
            "claimflow.services.alibaba_cloud_integration.verify_alibaba_cloud_connection",
            new_callable=AsyncMock,
            return_value={
                "status": "healthy",
                "alibaba_cloud_services": {
                    "qwen_cloud": {"status": "connected"},
                    "oss": {"status": "configured"},
                    "ram": {"status": "configured"},
                },
            },
        ),
    ):
        from claimflow.tools.factory import reset_storage_client_cache

        reset_storage_client_cache()
        from claimflow.api.main import create_app

        with TestClient(create_app(settings=test_settings)) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_storage_client_cache()


@pytest.mark.asyncio
async def test_claim_store_in_memory_roundtrip() -> None:
    from claimflow.db.session import Database
    from claimflow.services.claim_store import ClaimStore

    get_settings.cache_clear()
    settings = _build_test_settings()
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
        headers=_AUTH_HEADERS,
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
        ClaimStatus.HUMAN_REVIEW,
        {"fraud_risk_score": 0.8, "awaiting_human_decision": True},
    )

    response = client.post(
        "/api/v1/review/CLM-REV-004/decision",
        json={
            "decision": "approved",
            "analyst_notes": "Payment authorized after review.",
            "analyst_id": "demo-analyst",
        },
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["reviewer_note"] == "Payment authorized after review."


@pytest.mark.asyncio
async def test_review_decision_rejects_non_human_review_status(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-REV-006",
        ClaimStatus.APPROVED,
        {"fraud_risk_score": 0.2},
    )

    response = client.post(
        "/api/v1/review/CLM-REV-006/decision",
        json={"decision": "rejected", "analyst_notes": "too late"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 409


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
        headers=_AUTH_HEADERS,
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/review/CLM-REV-005/decision",
        json={"decision": "rejected", "analyst_notes": "Changed mind"},
        headers=_AUTH_HEADERS,
    )
    assert second.status_code == 409
