"""Tests for production-grade upload validation rules."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.api.file_validation import (
    MAX_UPLOAD_BYTES,
    FileValidationError,
    sanitize_filename,
    validate_extension,
    validate_file_size,
    validate_magic_bytes,
    validate_mime_type,
    validate_upload,
)
from claimflow.core.config import Settings, get_settings

_TEST_API_KEY = "cf_test_upload_val_9f8e7d6c5b4a3210"
_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}

# Minimal valid magic-number payloads (not full images — signatures only).
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 16
_WEBP = b"RIFF" + (24).to_bytes(4, "little") + b"WEBP" + b"\x00" * 12
_PDF = b"%PDF-1.4 fake"


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


def _mock_upload(
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> MagicMock:
    upload = MagicMock()
    upload.filename = filename
    upload.content_type = content_type

    async def _read(size: int = -1) -> bytes:
        nonlocal data
        if not data:
            return b""
        if size < 0:
            chunk, data = data, b""
            return chunk
        chunk, data = data[:size], data[size:]
        return chunk

    upload.read = _read
    return upload


# --- Unit: sanitize filename / path traversal ---


def test_sanitize_filename_strips_path_traversal() -> None:
    assert sanitize_filename("../../etc/passwd.png") == "passwd.png"
    assert sanitize_filename("..\\..\\windows\\evil.jpg") == "evil.jpg"
    assert sanitize_filename("/tmp/nested/photo.jpeg") == "photo.jpeg"


def test_sanitize_filename_rejects_empty_and_dot_names() -> None:
    with pytest.raises(FileValidationError) as exc:
        sanitize_filename("   ")
    assert exc.value.status_code == 400

    with pytest.raises(FileValidationError):
        sanitize_filename("../..")


def test_sanitize_filename_removes_null_bytes_and_unsafe_chars() -> None:
    assert sanitize_filename("claim\x00 photo!.png") == "claim_photo_.png"


# --- Unit: extension allowlist ---


def test_validate_extension_accepts_allowlist() -> None:
    for name in ("a.jpg", "b.JPEG", "c.png", "d.webp", "e.gif"):
        validate_extension(name)


def test_validate_extension_rejects_disallowed() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_extension("malware.exe")
    assert exc.value.status_code == 422
    assert ".exe" in exc.value.detail

    with pytest.raises(FileValidationError):
        validate_extension("readme")


# --- Unit: MIME ↔ extension ---


def test_validate_mime_type_must_match_extension() -> None:
    assert validate_mime_type("image/jpeg", ".jpg") == "image/jpeg"
    assert validate_mime_type("image/png; charset=binary", ".png") == "image/png"

    with pytest.raises(FileValidationError) as exc:
        validate_mime_type("image/png", ".jpg")
    assert exc.value.status_code == 422

    with pytest.raises(FileValidationError):
        validate_mime_type(None, ".png")


# --- Unit: magic bytes ---


def test_validate_magic_bytes_accepts_matching_signatures() -> None:
    validate_magic_bytes(_JPEG, ".jpg")
    validate_magic_bytes(_PNG, ".png")
    validate_magic_bytes(_GIF, ".gif")
    validate_magic_bytes(_WEBP, ".webp")


def test_validate_magic_bytes_rejects_spoofed_extension() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_magic_bytes(_PDF, ".png")
    assert exc.value.status_code == 422
    assert "magic" in exc.value.detail.lower()

    with pytest.raises(FileValidationError):
        validate_magic_bytes(_JPEG, ".png")


# --- Unit: size limit ---


def test_validate_file_size_allows_at_limit() -> None:
    validate_file_size(MAX_UPLOAD_BYTES)


def test_validate_file_size_rejects_over_limit() -> None:
    with pytest.raises(FileValidationError) as exc:
        validate_file_size(MAX_UPLOAD_BYTES + 1)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_validate_upload_happy_path() -> None:
    upload = _mock_upload(filename="damage.png", content_type="image/png", data=_PNG)
    result = await validate_upload(upload)
    assert result.filename == "damage.png"
    assert result.content_type == "image/png"
    assert result.data == _PNG


@pytest.mark.asyncio
async def test_validate_upload_enforces_size_while_reading() -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_UPLOAD_BYTES
    upload = _mock_upload(
        filename="huge.png",
        content_type="image/png",
        data=oversized,
    )
    with pytest.raises(FileValidationError) as exc:
        await validate_upload(upload)
    assert exc.value.status_code == 413


# --- Integration: POST /api/v1/uploads ---


def test_upload_endpoint_accepts_valid_png(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("damage.png", BytesIO(_PNG), "image/png")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "damage.png"
    assert body["content_type"] == "image/png"
    assert "url" in body


def test_upload_endpoint_rejects_oversized_file(client: TestClient) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_UPLOAD_BYTES
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("huge.png", BytesIO(payload), "image/png")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]


def test_upload_endpoint_rejects_bad_extension(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("notes.pdf", BytesIO(_PDF), "application/pdf")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "extension" in response.json()["detail"].lower()


def test_upload_endpoint_rejects_mime_mismatch(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("photo.jpg", BytesIO(_JPEG), "image/png")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "content-type" in response.json()["detail"].lower()


def test_upload_endpoint_rejects_magic_byte_spoof(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("fake.png", BytesIO(_PDF), "image/png")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "magic" in response.json()["detail"].lower()


def test_upload_endpoint_sanitizes_path_traversal_filename(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("../../evil.png", BytesIO(_PNG), "image/png")},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "evil.png"
