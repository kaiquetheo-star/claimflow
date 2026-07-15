"""Smoke tests for health and application bootstrap."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.core.config import Settings, get_settings

_TEST_PROJECT_NAME = "Claimflow Autopilot"


def _build_test_settings() -> Settings:
    """Return explicit Settings isolated from the developer's local ``.env`` file."""
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        project_name=_TEST_PROJECT_NAME,
        storage_backend="local",
        database_url=None,
        local_upload_dir="./test_uploads",
        use_mock_llm=False,
    )


def _mock_alibaba_cloud_status() -> dict[str, object]:
    return {
        "status": "healthy",
        "alibaba_cloud_services": {
            "qwen_cloud": {"status": "connected", "models_available": ["qwen-max", "qwen-vl-max"]},
            "oss": {"status": "configured", "backend": "local"},
            "ram": {"status": "configured", "access_key_set": True},
        },
    }


@pytest.fixture
def client() -> TestClient:
    test_settings = _build_test_settings()
    get_settings.cache_clear()

    with (
        patch("claimflow.core.config.get_settings", return_value=test_settings),
        patch("claimflow.api.routes.health.get_settings", return_value=test_settings),
        patch("claimflow.tools.factory.get_settings", return_value=test_settings),
        patch("claimflow.api.main.get_settings", return_value=test_settings),
        patch(
            "claimflow.api.routes.health.verify_alibaba_cloud_connection",
            new_callable=AsyncMock,
            return_value=_mock_alibaba_cloud_status(),
        ),
    ):
        from claimflow.api.main import create_app
        from claimflow.tools.factory import reset_storage_client_cache

        reset_storage_client_cache()
        app = create_app(settings=test_settings)
        with TestClient(app) as test_client:
            yield test_client

    get_settings.cache_clear()
    from claimflow.tools.factory import reset_storage_client_cache

    reset_storage_client_cache()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["project"] == _TEST_PROJECT_NAME
    assert "version" in body
    assert "environment" in body
    assert "alibaba_cloud_services" in body
    assert body["mock_mode"] is False

    services = body["alibaba_cloud_services"]
    assert services["qwen_cloud"]["status"] == "connected"
    assert services["oss"]["backend"] == "local"
    assert services["ram"]["access_key_set"] is True
