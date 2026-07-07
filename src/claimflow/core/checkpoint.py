"""LangGraph checkpoint lifecycle management."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from claimflow.core.config import Settings
from claimflow.core.logging import get_logger

logger = get_logger(__name__)


class CheckpointManager:
    """Initialise and tear down the LangGraph checkpointer on app startup/shutdown."""

    def __init__(self) -> None:
        self._checkpointer: BaseCheckpointSaver | None = None
        self._context: Any = None

    @property
    def checkpointer(self) -> BaseCheckpointSaver:
        """Return the active checkpointer (raises if not initialised)."""
        if self._checkpointer is None:
            msg = "CheckpointManager has not been started"
            raise RuntimeError(msg)
        return self._checkpointer

    @property
    def backend(self) -> str:
        """Return a human-readable label for the active checkpoint backend."""
        if isinstance(self._checkpointer, InMemorySaver):
            return "memory"
        return "postgres"

    async def startup(self, settings: Settings) -> None:
        """Create the checkpointer and run schema setup when using PostgreSQL."""
        checkpoint_url = settings.langgraph_checkpoint_url

        if checkpoint_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            self._context = AsyncPostgresSaver.from_conn_string(checkpoint_url)
            self._checkpointer = await self._context.__aenter__()
            await self._checkpointer.setup()
            logger.info(
                "LangGraph PostgreSQL checkpoint initialised",
                extra={"backend": "postgres"},
            )
        else:
            self._checkpointer = InMemorySaver()
            logger.info(
                "LangGraph in-memory checkpoint initialised",
                extra={"backend": "memory"},
            )

    async def shutdown(self) -> None:
        """Release PostgreSQL checkpoint resources."""
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
            self._context = None
        self._checkpointer = None
        logger.info("Checkpoint manager shut down")
