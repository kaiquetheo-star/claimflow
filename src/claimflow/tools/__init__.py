"""File storage strategy implementations (local filesystem, Alibaba OSS)."""

from claimflow.tools.factory import get_storage_client
from claimflow.tools.storage_interface import BaseStorage

__all__ = ["BaseStorage", "get_storage_client"]
