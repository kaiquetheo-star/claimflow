"""Alibaba Cloud OSS storage backend."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.credentials import StaticCredentialsProvider

from claimflow.core.config import Settings
from claimflow.core.logging import get_logger
from claimflow.tools.storage_interface import BaseStorage

logger = get_logger(__name__)


class OSSStorageError(Exception):
    """Raised when an OSS operation fails."""


class OSSStorage(BaseStorage):
    """Alibaba Cloud OSS storage strategy using ``alibabacloud-oss-v2``.

    Ready for production once the OSS account billing/risk-control review completes.
    Set ``STORAGE_BACKEND=oss`` to activate.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = self._build_client()
        logger.info(
            "OSSStorage initialised",
            extra={
                "bucket": settings.oss_bucket_name,
                "endpoint": settings.oss_endpoint,
                "region": settings.oss_region,
            },
        )

    def _build_client(self) -> oss.Client:
        credentials = StaticCredentialsProvider(
            access_key_id=self._settings.alibaba_cloud_access_key_id.get_secret_value(),
            access_key_secret=self._settings.alibaba_cloud_access_key_secret.get_secret_value(),
        )
        config = oss.Config(
            region=self._settings.oss_region,
            endpoint=self._settings.oss_endpoint,
            credentials_provider=credentials,
        )
        return oss.Client(config)

    def _safe_filename(self, filename: str) -> str:
        return Path(filename).name

    def _object_key(self, filename: str) -> str:
        prefix = self._settings.oss_object_prefix.rstrip("/")
        return f"{prefix}/{self._safe_filename(filename)}"

    async def upload_file(self, file_bytes: bytes, filename: str) -> str:
        """Upload bytes to OSS and return a pre-signed download URL."""
        key = self._object_key(filename)
        request = oss.models.PutObjectRequest(
            bucket=self._settings.oss_bucket_name,
            key=key,
            body=file_bytes,
        )

        try:
            await asyncio.to_thread(self._client.put_object, request)
        except Exception as exc:
            logger.error("OSS upload failed", extra={"key": key, "error": str(exc)})
            raise OSSStorageError(f"OSS upload failed: {exc}") from exc

        url = await self.get_file_url(filename)
        logger.info(
            "File uploaded to OSS",
            extra={"key": key, "size_bytes": len(file_bytes), "url": url},
        )
        return url

    async def get_file_url(self, filename: str) -> str:
        """Return a pre-signed GET URL for the object."""
        key = self._object_key(filename)
        request = oss.models.GetObjectRequest(
            bucket=self._settings.oss_bucket_name,
            key=key,
        )
        expires = datetime.timedelta(seconds=self._settings.oss_presign_expiry_seconds)

        try:
            result = await asyncio.to_thread(
                self._client.presign,
                request,
                expires=expires,
            )
        except Exception as exc:
            logger.error("OSS presign failed", extra={"key": key, "error": str(exc)})
            raise OSSStorageError(f"OSS presign failed: {exc}") from exc

        if not result.url:
            raise OSSStorageError("OSS presign returned an empty URL")
        return result.url
