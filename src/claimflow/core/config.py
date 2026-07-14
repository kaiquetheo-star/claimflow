"""Application configuration loaded from environment variables."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings sourced from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Alibaba Cloud / DashScope ---
    dashscope_api_key: SecretStr = Field(
        ...,
        description="API key for Alibaba Cloud DashScope (Qwen LLM).",
    )
    llm_base_url: str = Field(
        default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        description="OpenAI-compatible base URL for DashScope/Qwen.",
    )
    llm_model_name: str = Field(
        default="qwen-turbo",
        description="Primary Qwen model for triage, investigation, and risk assessment.",
    )
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["qwen-plus", "qwen-turbo"],
        description="Fallback Qwen models tried when the primary model is unavailable.",
    )
    vision_model_name: str = Field(
        default="qwen-vl-max",
        description="Primary Qwen-VL model identifier for multimodal image analysis.",
    )
    vision_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["qwen-vl-plus"],
        description="Fallback Qwen-VL models when the primary vision model is unavailable.",
    )
    vision_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Maximum seconds to wait for a Qwen-VL API response.",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Maximum seconds to wait for a Qwen text LLM API response.",
    )
    use_mock_llm: bool = Field(
        default=False,
        description=(
            "When true, skip DashScope calls and use MockLLM deterministic scenarios "
            "for demos and testing."
        ),
    )
    risk_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Score threshold above which a claim is routed to human review.",
    )
    reject_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Score threshold above which a claim is automatically rejected.",
    )
    alibaba_cloud_access_key_id: SecretStr = Field(
        ...,
        description="Alibaba Cloud IAM access key ID.",
    )
    alibaba_cloud_access_key_secret: SecretStr = Field(
        ...,
        description="Alibaba Cloud IAM access key secret.",
    )

    # --- OSS ---
    oss_bucket_name: str = Field(
        ...,
        description="Alibaba Cloud OSS bucket name for claim documents.",
    )
    oss_endpoint: str = Field(
        ...,
        description="OSS endpoint URL (e.g. https://oss-cn-hangzhou.aliyuncs.com).",
    )
    oss_region: str = Field(
        default="cn-hangzhou",
        description="Alibaba Cloud region for OSS API signing (e.g. cn-hangzhou).",
    )
    oss_presign_expiry_seconds: int = Field(
        default=3600,
        ge=60,
        description="Pre-signed OSS URL validity in seconds.",
    )
    oss_object_prefix: str = Field(
        default="claims/",
        description="Key prefix for claim documents stored in OSS.",
    )

    # --- Database / checkpointing ---
    # PostgreSQL is the default persistence backend. Set DATABASE_URL= (empty) to
    # fall back to the in-memory claim store for quick local testing.
    database_url: str | None = Field(
        default="postgresql://claimflow:claimflow@localhost:5432/claimflow",
        description=(
            "PostgreSQL URL for claim snapshots. When set, ClaimStore uses Postgres; "
            "when empty/None, falls back to in-memory storage."
        ),
    )
    checkpoint_database_url: str | None = Field(
        default=None,
        description=(
            "PostgreSQL URL for LangGraph checkpoints (psycopg format). Falls back to database_url."
        ),
    )

    # --- Storage strategy ---
    storage_backend: Literal["local", "oss"] = Field(
        default="local",
        description="Active file storage backend: 'local' or 'oss'.",
    )
    local_upload_dir: str = Field(
        default="./uploads",
        description="Directory for local file uploads when storage_backend=local.",
    )
    local_upload_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL prepended to local upload paths for synthetic cloud URLs.",
    )

    # --- Application ---
    api_key: SecretStr = Field(
        default=SecretStr("cf_hk_a8f3b2c19e4d5f60718293a4b5c6d7e8"),
        description=(
            "Shared API key required via X-API-Key header on mutating endpoints "
            "(claims submit, uploads, review decisions). Rotate for production."
        ),
    )
    api_v1_str: str = Field(
        default="/api/v1",
        description="URL prefix for versioned API routes.",
    )
    project_name: str = Field(
        default="Claimflow Autopilot",
        description="Human-readable project name shown in API docs.",
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Root logging level.",
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins.",
    )

    @field_validator("llm_fallback_models", "vision_fallback_models", "cors_origins", mode="before")
    @classmethod
    def _parse_string_list(cls, value: object) -> object:
        """Accept JSON arrays or comma-separated strings from environment variables."""
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("database_url", "checkpoint_database_url", mode="before")
    @classmethod
    def _empty_url_to_none(cls, value: object) -> object:
        """Treat blank env values as unset (enables in-memory fallback)."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def llm_models(self) -> list[str]:
        """Primary LLM followed by fallbacks, deduplicated."""
        seen: set[str] = set()
        chain: list[str] = []
        for model in [self.llm_model_name, *self.llm_fallback_models]:
            if model and model not in seen:
                seen.add(model)
                chain.append(model)
        return chain

    @property
    def vision_models(self) -> list[str]:
        """Primary vision model followed by fallbacks, deduplicated."""
        seen: set[str] = set()
        chain: list[str] = []
        for model in [self.vision_model_name, *self.vision_fallback_models]:
            if model and model not in seen:
                seen.add(model)
                chain.append(model)
        return chain

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.environment == "production"

    @property
    def uses_postgres(self) -> bool:
        """Return True when a PostgreSQL database URL is configured."""
        return bool(self.database_url)

    @property
    def sqlalchemy_database_url(self) -> str | None:
        """Return the database URL normalised for SQLAlchemy asyncpg."""
        if not self.database_url:
            return None
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def langgraph_checkpoint_url(self) -> str | None:
        """Return the database URL for LangGraph AsyncPostgresSaver (psycopg)."""
        raw = self.checkpoint_database_url or self.database_url
        if not raw:
            return None
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
