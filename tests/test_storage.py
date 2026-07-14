"""Tests for the storage strategy pattern and upload endpoints."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.core.config import Settings, get_settings


_TEST_API_KEY = "cf_hk_a8f3b2c19e4d5f60718293a4b5c6d7e8"
_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}


def _build_test_settings(upload_dir: str) -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        api_key=SecretStr(_TEST_API_KEY),
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
        patch("claimflow.api.dependencies.get_settings", return_value=test_settings),
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


@pytest.mark.asyncio
async def test_local_materialize_local_path_for_vision(tmp_path: Path) -> None:
    from claimflow.tools.local_storage import LocalStorage

    upload_dir = tmp_path / "files"
    storage = LocalStorage(upload_dir=upload_dir, base_url="http://localhost:8000")
    await storage.upload_file(b"\xff\xd8\xff local-jpeg", "photo.jpg")

    path_str, is_temporary = await storage.materialize_local_path("photo.jpg")

    assert is_temporary is False
    assert Path(path_str).is_file()
    assert Path(path_str).read_bytes() == b"\xff\xd8\xff local-jpeg"


@pytest.mark.asyncio
async def test_resolve_image_path_supports_local_and_oss_backends(tmp_path: Path) -> None:
    """Vision preprocessing must yield a real local file for local and OSS storage."""
    from unittest.mock import MagicMock

    from claimflow.api.routes.claims import _resolve_image_path
    from claimflow.tools.local_storage import LocalStorage
    from claimflow.tools.oss_storage import OSSStorage

    # --- Local backend ---
    local = LocalStorage(upload_dir=tmp_path / "uploads", base_url="http://localhost:8000")
    await local.upload_file(b"\xff\xd8\xff local", "local.jpg")
    local_path, local_tmp = await _resolve_image_path("local.jpg", local)
    assert local_tmp is False
    assert Path(local_path).is_file()

    # --- OSS backend (mocked download) ---
    with patch.dict(
        "os.environ",
        {
            "DASHSCOPE_API_KEY": "test-key",
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
            "OSS_BUCKET_NAME": "test-bucket",
            "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
        },
        clear=False,
    ):
        from claimflow.core.config import get_settings

        get_settings.cache_clear()
        oss = OSSStorage(get_settings())
        get_settings.cache_clear()

    mock_body = MagicMock()
    mock_body.read = MagicMock(return_value=b"\xff\xd8\xff oss")
    mock_result = MagicMock()
    mock_result.body = mock_body

    with patch.object(oss._client, "get_object", return_value=mock_result):
        oss_path, oss_tmp = await _resolve_image_path("oss.jpg", oss)

    try:
        assert oss_tmp is True
        assert Path(oss_path).is_file()
        assert Path(oss_path).read_bytes() == b"\xff\xd8\xff oss"
    finally:
        Path(oss_path).unlink(missing_ok=True)


def test_upload_endpoint(client: TestClient, upload_dir: Path) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("report.pdf", BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        headers=_AUTH_HEADERS,
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
