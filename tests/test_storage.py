"""Tests for the storage strategy pattern and upload endpoints."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.core.config import Settings, get_settings


def _build_test_settings(upload_dir: str) -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        storage_backend="local",
        local_upload_dir=upload_dir,
        local_upload_base_url="http://localhost:8000",
    )


@pytest.fixture
def upload_dir(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def client(upload_dir: Path) -> TestClient:
    test_settings = _build_test_settings(str(upload_dir))

    with (
        patch("claimflow.core.config.get_settings", return_value=test_settings),
        patch("claimflow.tools.factory.get_settings", return_value=test_settings),
    ):
        from claimflow.tools.factory import reset_storage_client_cache

        get_settings.cache_clear()
        reset_storage_client_cache()

        from claimflow.api.main import create_app

        app = create_app(settings=test_settings)
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


def test_upload_endpoint(client: TestClient, upload_dir: Path) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("report.pdf", BytesIO(b"%PDF-1.4 test"), "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "report.pdf"
    assert body["url"] == "http://localhost:8000/uploads/report.pdf"
    assert (upload_dir / "report.pdf").exists()


def test_static_file_served_at_uploads_path(client: TestClient, upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "photo.jpg").write_bytes(b"fake-image")

    response = client.get("/uploads/photo.jpg")
    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_factory_selects_local_backend() -> None:
    test_settings = _build_test_settings("./test_uploads")

    with (
        patch("claimflow.core.config.get_settings", return_value=test_settings),
        patch("claimflow.tools.factory.get_settings", return_value=test_settings),
    ):
        from claimflow.tools.factory import get_storage_client, reset_storage_client_cache
        from claimflow.tools.local_storage import LocalStorage

        get_settings.cache_clear()
        reset_storage_client_cache()

        client = get_storage_client()
        assert isinstance(client, LocalStorage)

        get_settings.cache_clear()
        reset_storage_client_cache()
