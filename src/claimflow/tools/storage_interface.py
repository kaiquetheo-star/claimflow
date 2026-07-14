"""Abstract storage interface for claim document persistence."""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class BaseStorage(ABC):
    """Strategy interface for uploading and resolving claim document URLs.

    Implementations may target a local filesystem (development) or a cloud
    object store such as Alibaba OSS (production).
    """

    @abstractmethod
    async def upload_file(self, file_bytes: bytes, filename: str) -> str:
        """Persist raw file bytes and return a publicly resolvable URL or path.

        Args:
            file_bytes: Raw content of the uploaded file.
            filename: Original or sanitised file name (no directory components).

        Returns:
            URL or path that can be used to retrieve the file later.
        """

    @abstractmethod
    async def get_file_url(self, filename: str) -> str:
        """Return the URL or path for a previously uploaded file.

        Args:
            filename: File name as stored by the backend.

        Returns:
            URL or path pointing to the file.
        """

    @abstractmethod
    async def download_file(self, filename: str) -> bytes:
        """Download previously uploaded file bytes.

        Args:
            filename: File name as stored by the backend.

        Returns:
            Raw file content.
        """

    async def materialize_local_path(self, filename: str) -> tuple[str, bool]:
        """Return a local filesystem path suitable for Qwen-VL analysis.

        Local backends return the on-disk path. Remote backends (e.g. OSS)
        download the object into a temporary file.

        Returns:
            Tuple of ``(absolute_path, is_temporary)``. When ``is_temporary`` is
            True the caller must delete the file after use.
        """
        file_bytes = await self.download_file(filename)
        suffix = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(
            prefix="claimflow_vision_",
            suffix=suffix,
            delete=False,
        ) as tmp:
            tmp.write(file_bytes)
            return tmp.name, True
