"""Abstract storage interface for claim document persistence."""

from abc import ABC, abstractmethod


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
