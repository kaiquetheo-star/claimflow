"""API key authentication tests for mutating endpoints."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.agents.states import ClaimStatus
from claimflow.core.config import Settings, get_settings

_TEST_API_KEY = "cf_test_auth_key_9f8e7d6c5b4a3210"
_BAD_API_KEY = "definitely-wrong-api-key!"


def _build_test_settings(upload_dir: str) -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        api_key=SecretStr(_TEST_API_KEY),
        storage_backend="local",
        database_url=None,
        local_upload_dir=upload_dir,
        use_mock_llm=True,
    )


def _auth_headers(key: str = _TEST_API_KEY) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    test_settings = _build_test_settings(str(tmp_path / "uploads"))
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
                    "oss": {"status": "configured", "backend": "local"},
                    "ram": {"status": "configured"},
                },
            },
        ),
    ):
        from claimflow.tools.factory import reset_storage_client_cache

        reset_storage_client_cache()
        from claimflow.api.main import create_app

        app = create_app(settings=test_settings)
        with TestClient(app) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_storage_client_cache()


def test_health_remains_public(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_upload_requires_api_key_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("report.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code == 401
    assert "API key" in response.json()["detail"]


def test_upload_rejects_invalid_api_key_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("report.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")},
        headers=_auth_headers(_BAD_API_KEY),
    )
    assert response.status_code == 401


def test_upload_with_valid_api_key_returns_201(client: TestClient) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("photo.png", BytesIO(png), "image/png")},
        headers=_auth_headers(),
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "photo.png"


@pytest.mark.asyncio
async def test_review_decision_requires_api_key_returns_401(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-AUTH-001",
        ClaimStatus.HUMAN_REVIEW,
        {"fraud_risk_score": 0.8, "awaiting_human_decision": True},
    )

    response = client.post(
        "/api/v1/review/CLM-AUTH-001/decision",
        json={"decision": "REJECTED", "analyst_notes": "no key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_review_decision_with_valid_api_key_returns_200(client: TestClient) -> None:
    store = client.app.state.claim_store
    await store.save_result(
        "CLM-AUTH-002",
        ClaimStatus.HUMAN_REVIEW,
        {"fraud_risk_score": 0.8, "awaiting_human_decision": True},
    )

    response = client.post(
        "/api/v1/review/CLM-AUTH-002/decision",
        json={"decision": "REJECTED", "analyst_notes": "fraud"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_claims_submit_requires_api_key_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/claims/submit",
        data={"claim_id": "CLM-AUTH-003", "raw_input_text": "teste sem chave"},
    )
    assert response.status_code == 401
