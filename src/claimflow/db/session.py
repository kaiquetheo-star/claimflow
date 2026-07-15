"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from claimflow.core.config import Settings
from claimflow.core.logging import get_logger

logger = get_logger(__name__)


class Database:
    """Manage the async SQLAlchemy engine lifecycle."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_configured(self) -> bool:
        return self._engine is not None

    async def startup(self, settings: Settings) -> None:
        """Create the async engine when ``DATABASE_URL`` points at PostgreSQL.

        Schema is managed by Alembic (``make migrate`` / ``alembic upgrade head``).
        """
        url = settings.sqlalchemy_database_url
        if not url:
            logger.info("Claim store backend: InMemory (no DATABASE_URL)")
            return

        logger.info("Claim store backend: PostgreSQL")
        self._engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

        logger.info(
            "PostgreSQL claim store engine ready",
            extra={"backend": "postgres"},
        )

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._session_factory is None:
            msg = "Database is not configured"
            raise RuntimeError(msg)
        async with self._session_factory() as session:
            yield session
