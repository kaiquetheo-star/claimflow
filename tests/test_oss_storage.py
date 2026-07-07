"""Unit tests for Alibaba OSS storage backend."""

import os
from unittest.mock import MagicMock, patch

import pytest

from claimflow.tools.oss_storage import OSSStorage, OSSStorageError

_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-cn-hangzhou.aliyuncs.com",
}


@pytest.fixture(autouse=True)
def _settings() -> None:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_oss_upload_and_presign() -> None:
    from claimflow.core.config import get_settings

    settings = get_settings()
    storage = OSSStorage(settings)

    mock_presign = MagicMock()
    mock_presign.url = "https://signed-url.example.com/claims/doc.pdf"

    with (
        patch.object(storage._client, "put_object") as mock_put,
        patch.object(
            storage._client,
            "presign",
            return_value=mock_presign,
        ),
    ):
        url = await storage.upload_file(b"pdf-bytes", "doc.pdf")

    assert url == "https://signed-url.example.com/claims/doc.pdf"
    mock_put.assert_called_once()


@pytest.mark.asyncio
async def test_oss_upload_failure() -> None:
    from claimflow.core.config import get_settings

    settings = get_settings()
    storage = OSSStorage(settings)

    with (
        patch.object(storage._client, "put_object", side_effect=RuntimeError("blocked")),
        pytest.raises(OSSStorageError, match="OSS upload failed"),
    ):
        await storage.upload_file(b"data", "file.jpg")
