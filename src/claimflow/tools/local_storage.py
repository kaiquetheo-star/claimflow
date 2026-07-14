"""Local filesystem storage backend for development and testing."""

import asyncio
from pathlib import Path

from claimflow.core.logging import get_logger
from claimflow.tools.storage_interface import BaseStorage

logger = get_logger(__name__)


class LocalStorage(BaseStorage):
    """Store uploaded files on the local filesystem under a configurable directory.

    Returns synthetic cloud-style URLs (e.g. ``http://localhost:8000/uploads/doc.pdf``)
    so downstream consumers behave identically to a production OSS deployment.
    """

    def __init__(self, upload_dir: Path, base_url: str) -> None:
        self._upload_dir = upload_dir
        self._base_url = base_url.rstrip("/")
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "LocalStorage initialised",
            extra={"upload_dir": str(self._upload_dir.resolve()), "base_url": self._base_url},
        )

    @property
    def upload_dir(self) -> Path:
        """Absolute path to the directory where files are stored."""
        return self._upload_dir

    def _safe_filename(self, filename: str) -> str:
        """Strip path components to prevent directory traversal attacks."""
        return Path(filename).name

    async def upload_file(self, file_bytes: bytes, filename: str) -> str:
        safe_name = self._safe_filename(filename)
        target = self._upload_dir / safe_name

        await asyncio.to_thread(target.write_bytes, file_bytes)

        url = await self.get_file_url(safe_name)
        logger.info(
            "File uploaded to local storage",
            extra={"filename": safe_name, "size_bytes": len(file_bytes), "url": url},
        )
        return url

    async def get_file_url(self, filename: str) -> str:
        safe_name = self._safe_filename(filename)
        return f"{self._base_url}/uploads/{safe_name}"

    async def download_file(self, filename: str) -> bytes:
        path = self.resolve_local_path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Local storage file not found: {path}")
        return await asyncio.to_thread(path.read_bytes)

    def resolve_local_path(self, filename: str) -> Path:
        """Return the absolute local filesystem path for a stored filename."""
        return (self._upload_dir / self._safe_filename(filename)).resolve()

    async def materialize_local_path(self, filename: str) -> tuple[str, bool]:
        """Return the existing local path without copying to a temp file."""
        path = self.resolve_local_path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Local storage file not found: {path}")
        return str(path), False
