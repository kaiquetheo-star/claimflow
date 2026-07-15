"""Factory for resolving the active storage backend from application settings."""

from pathlib import Path

from claimflow.core.config import Settings, get_settings
from claimflow.core.logging import get_logger
from claimflow.tools.local_storage import LocalStorage
from claimflow.tools.oss_storage import OSSStorage
from claimflow.tools.storage_interface import BaseStorage

logger = get_logger(__name__)

# Module-level cache: Settings is not hashable, so we cannot put it in @lru_cache keys.
_storage_client: BaseStorage | None = None


def get_storage_client(settings: Settings | None = None) -> BaseStorage:
    """Return a cached storage client based on ``STORAGE_BACKEND``.

    Args:
        settings: Optional settings override. When provided, builds (and caches)
            the client from these settings without calling ``get_settings()``.
            Prefer this in app lifespan and tests so API keys aren't required.

    Supported values:
        - ``local`` (default): :class:`LocalStorage` writing to ``LOCAL_UPLOAD_DIR``.
        - ``oss``: :class:`OSSStorage` (stub until account verification completes).

    Returns:
        Configured :class:`BaseStorage` implementation.

    Raises:
        ValueError: If ``STORAGE_BACKEND`` is not a recognised value.
    """
    global _storage_client

    if settings is None and _storage_client is not None:
        return _storage_client

    resolved = settings or get_settings()
    backend = resolved.storage_backend

    if backend == "local":
        client: BaseStorage = LocalStorage(
            upload_dir=Path(resolved.local_upload_dir),
            base_url=resolved.local_upload_base_url,
        )
    elif backend == "oss":
        client = OSSStorage(resolved)
    else:
        msg = f"Unknown STORAGE_BACKEND: {backend!r}. Expected 'local' or 'oss'."
        raise ValueError(msg)

    logger.info(
        "Storage backend selected",
        extra={"storage_backend": backend, "client_class": type(client).__name__},
    )
    _storage_client = client
    return client


def reset_storage_client_cache() -> None:
    """Clear the cached storage client (useful in tests)."""
    global _storage_client
    _storage_client = None
