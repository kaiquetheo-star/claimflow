"""Tests for the storage strategy pattern and upload endpoints."""

import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
    "STORAGE_BACKEND": "local",
    "LOCAL_UPLOAD_DIR": "./test_uploads",
    "LOCAL_UPLOAD_BASE_URL": "http://localhost:8000",
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    env = {**_ENV_PATCH, "LOCAL_UPLOAD_DIR": str(tmp_path / "uploads")}
    with patch.dict(os.environ, env, clear=False):
        from claimflow.core.config import get_settings
        from claimflow.tools.factory import reset_storage_client_cache

        get_settings.cache_clear()
        reset_storage_client_cache()

        from claimflow.api.main import create_app

        app = create_app()
        with TestClient(app) as test_client:
            yield test_client

        get_settings.cache_clear()
        reset_storage_client_cache()


@pytest.mark.asyncio
async def test_local_storage_upload_and_url(tmp_path: Path) -> None:
    from claimflow.tools.local_storage import LocalStorage

    upload_dir = tmp_path / "files"
    storage = LocalStorage(upload_dir=upload_dir, base_url="http://localhost:8000")

    url = await storage.upload_file(b"hello world", "doc.txt")
    assert url == "http://localhost:8000/uploads/doc.txt"
    assert (upload_dir / "doc.txt").read_bytes() == b"hello world"

    assert await storage.get_file_url("doc.txt") == "http://localhost:8000/uploads/doc.txt"


def test_upload_endpoint(client: TestClient, tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("report.pdf", BytesIO(b"%PDF-1.4 test"), "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "report.pdf"
    assert body["url"] == "http://localhost:8000/uploads/report.pdf"
    assert (upload_dir / "report.pdf").exists()


def test_static_file_served_at_uploads_path(client: TestClient, tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "photo.jpg").write_bytes(b"fake-image")

    response = client.get("/uploads/photo.jpg")
    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_factory_selects_local_backend() -> None:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings
        from claimflow.tools.factory import get_storage_client, reset_storage_client_cache
        from claimflow.tools.local_storage import LocalStorage

        get_settings.cache_clear()
        reset_storage_client_cache()

        client = get_storage_client()
        assert isinstance(client, LocalStorage)

        get_settings.cache_clear()
        reset_storage_client_cache()
