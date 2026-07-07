"""Smoke tests for health and application bootstrap."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Minimal env vars required by Settings before the app can start
_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
}


@pytest.fixture
def client() -> TestClient:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings

        get_settings.cache_clear()

        from claimflow.api.main import create_app

        app = create_app()
        with TestClient(app) as test_client:
            yield test_client

        get_settings.cache_clear()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["project"] == "Claimflow Autopilot"
