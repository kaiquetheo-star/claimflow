"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from claimflow import __version__
from claimflow.agents.graph import build_claim_graph
from claimflow.api.routes import claims_router, health_router, review_router, uploads_router
from claimflow.core.checkpoint import CheckpointManager
from claimflow.core.config import Settings, get_settings
from claimflow.core.logging import get_logger, setup_logging
from claimflow.db.session import Database
from claimflow.services.alibaba_cloud_integration import verify_alibaba_cloud_connection
from claimflow.services.claim_store import ClaimStore
from claimflow.tools.factory import get_storage_client, reset_storage_client_cache

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle hooks."""
    settings: Settings = app.state.settings
    setup_logging(settings)

    checkpoint_manager = CheckpointManager()
    database = Database()
    claim_store = ClaimStore()

    await database.startup(settings)
    await checkpoint_manager.startup(settings)
    await claim_store.startup(settings, database)

    app.state.checkpoint_manager = checkpoint_manager
    app.state.database = database
    app.state.claim_store = claim_store
    app.state.claim_graph = build_claim_graph(checkpointer=checkpoint_manager.checkpointer)
    app.state.checkpoint_backend = checkpoint_manager.backend
    app.state.claim_store_backend = claim_store.backend

    storage = get_storage_client()
    logger.info(
        "Application starting",
        extra={
            "environment": settings.environment,
            "storage_backend": settings.storage_backend,
            "storage_client": type(storage).__name__,
            "checkpoint_backend": checkpoint_manager.backend,
            "claim_store_backend": claim_store.backend,
            "use_mock_llm": settings.use_mock_llm,
        },
    )
    if settings.use_mock_llm:
        alibaba_status = await verify_alibaba_cloud_connection(settings)
        qwen_status = alibaba_status["alibaba_cloud_services"]["qwen_cloud"].get("status", "")
        dashscope_line = (
            "✅ CONNECTED (health check passed)"
            if qwen_status == "connected"
            else "⚠️  UNREACHABLE (check credentials)"
        )
        logger.info(
            "\n"
            "╔═══════════════════════════════════════════════════════════╗\n"
            "║ 🎭 DEMO MODE ACTIVE — Using MockLLM                       ║\n"
            f"║ Real DashScope API: {dashscope_line:<38} ║\n"
            "║ AI Inference: 🎭 MockLLM (deterministic scenarios)        ║\n"
            "║ Switch to production: USE_MOCK_LLM=false                ║\n"
            "╚═══════════════════════════════════════════════════════════╝"
        )
    yield

    await claim_store.shutdown()
    await checkpoint_manager.shutdown()
    await database.shutdown()
    reset_storage_client_cache()
    logger.info("Application shutting down")


def _mount_local_static_files(app: FastAPI, settings: Settings) -> None:
    """Expose the local upload directory at ``/uploads`` for static file serving."""
    if settings.storage_backend != "local":
        return

    upload_dir = Path(settings.local_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    app.mount(
        "/uploads",
        StaticFiles(directory=str(upload_dir.resolve())),
        name="uploads",
    )
    logger.info(
        "StaticFiles mounted for local uploads",
        extra={"mount_path": "/uploads", "directory": str(upload_dir.resolve())},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application instance.

    Args:
        settings: Optional settings override (useful for testing).

    Returns:
        Configured FastAPI application.
    """
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title=resolved_settings.project_name,
        version=__version__,
        openapi_url=f"{resolved_settings.api_v1_str}/openapi.json",
        docs_url=f"{resolved_settings.api_v1_str}/docs",
        redoc_url=f"{resolved_settings.api_v1_str}/redoc",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix=resolved_settings.api_v1_str)
    app.include_router(claims_router, prefix=resolved_settings.api_v1_str)
    app.include_router(uploads_router, prefix=resolved_settings.api_v1_str)
    app.include_router(review_router, prefix=resolved_settings.api_v1_str)

    _mount_local_static_files(app, resolved_settings)

    return app


app = create_app()


def run() -> None:
    """CLI entry point: start the uvicorn ASGI server."""
    settings = get_settings()
    uvicorn.run(
        "claimflow.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
        factory=False,
    )


if __name__ == "__main__":
    run()
