"""Factory for resolving the active storage backend from application settings."""

from functools import lru_cache
from pathlib import Path

from claimflow.core.config import get_settings
from claimflow.core.logging import get_logger
from claimflow.tools.local_storage import LocalStorage
from claimflow.tools.oss_storage import OSSStorage
from claimflow.tools.storage_interface import BaseStorage

logger = get_logger(__name__)


@lru_cache
def get_storage_client() -> BaseStorage:
    """Return a cached storage client based on ``STORAGE_BACKEND``.

    Supported values:
        - ``local`` (default): :class:`LocalStorage` writing to ``LOCAL_UPLOAD_DIR``.
        - ``oss``: :class:`OSSStorage` (stub until account verification completes).

    Returns:
        Configured :class:`BaseStorage` implementation.

    Raises:
        ValueError: If ``STORAGE_BACKEND`` is not a recognised value.
    """
    settings = get_settings()
    backend = settings.storage_backend

    if backend == "local":
        client: BaseStorage = LocalStorage(
            upload_dir=Path(settings.local_upload_dir),
            base_url=settings.local_upload_base_url,
        )
    elif backend == "oss":
        client = OSSStorage(settings)
    else:
        msg = f"Unknown STORAGE_BACKEND: {backend!r}. Expected 'local' or 'oss'."
        raise ValueError(msg)

    logger.info(
        "Storage backend selected",
        extra={"storage_backend": backend, "client_class": type(client).__name__},
    )
    return client


def reset_storage_client_cache() -> None:
    """Clear the cached storage client (useful in tests)."""
    get_storage_client.cache_clear()
