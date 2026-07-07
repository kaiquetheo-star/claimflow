"""Central registry and health verification for Alibaba Cloud integrations.

Claimflow runs on FastAPI + LangGraph locally but delegates AI inference, object
storage, and credential management to Alibaba Cloud services. This module
documents every integration point and exposes :func:`verify_alibaba_cloud_connection`
for operational health checks (e.g. hackathon proof via ``GET /api/v1/health``).

Services covered
----------------
1. **Qwen Cloud (DashScope)** — Alibaba Cloud's flagship AI platform for LLM and
   multimodal vision APIs.
2. **Alibaba Cloud OSS** — Object Storage Service for claim images and documents.
3. **Alibaba Cloud RAM** — Resource Access Management for least-privilege API keys.

See also: ``docs/ALIBABA_CLOUD_PROOF.md`` for judge-facing proof documentation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import alibabacloud_oss_v2 as oss
import httpx
from alibabacloud_oss_v2.credentials import StaticCredentialsProvider

from claimflow.core.config import Settings, get_settings
from claimflow.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# a) Qwen Cloud (DashScope) Integration
# ---------------------------------------------------------------------------
# Alibaba Cloud DashScope is the managed API gateway for Qwen foundation models.
# Claimflow uses the OpenAI-compatible endpoint for text (via LangChain ChatTongyi)
# and the native DashScope SDK for multimodal vision (Qwen-VL).
#
# API endpoint (international region):
#   https://dashscope-intl.aliyuncs.com/compatible-mode/v1
#
# Primary models:
#   - qwen-max      → structured text extraction (triage, risk assessment)
#   - qwen-vl-max   → vision analysis of uploaded damage photos
#
# Implementation references:
#   - src/claimflow/services/llm_service.py      (ChatTongyi / qwen-max)
#   - src/claimflow/services/vision_service.py   (AioMultiModalConversation / qwen-vl-max)
#
# Example — text LLM via LangChain ChatTongyi (DashScope backend):
#
#     from langchain_community.chat_models.tongyi import ChatTongyi
#
#     llm = ChatTongyi(
#         model="qwen-max",
#         api_key=settings.dashscope_api_key.get_secret_value(),
#         temperature=0.1,
#     )
#     structured = llm.with_structured_output(TriageResult)
#     result = await structured.ainvoke(messages)
#
# Example — vision via native DashScope SDK:
#
#     from dashscope import AioMultiModalConversation
#
#     response = await AioMultiModalConversation.call(
#         model="qwen-vl-max",
#         messages=messages,
#         api_key=settings.dashscope_api_key.get_secret_value(),
#         temperature=0.1,
#         result_format="message",
#     )

DASHSCOPE_COMPATIBLE_API_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
QWEN_TEXT_MODELS: tuple[str, ...] = ("qwen-max", "qwen-plus", "qwen-turbo")
QWEN_VISION_MODELS: tuple[str, ...] = ("qwen-vl-max", "qwen-vl-plus")
QWEN_PRIMARY_MODELS: tuple[str, ...] = ("qwen-max", "qwen-vl-max")

# ---------------------------------------------------------------------------
# b) Alibaba Cloud OSS Integration
# ---------------------------------------------------------------------------
# Production file storage uses Alibaba Cloud OSS via the official v2 SDK.
# Development uses LocalStorage — both implement :class:`BaseStorage` (Strategy
# Pattern). Switch backends with ``STORAGE_BACKEND=local|oss``.
#
# SDK imports (see src/claimflow/tools/oss_storage.py):
#
#     import alibabacloud_oss_v2 as oss
#     from alibabacloud_oss_v2.credentials import StaticCredentialsProvider
#
#     credentials = StaticCredentialsProvider(
#         access_key_id=settings.alibaba_cloud_access_key_id.get_secret_value(),
#         access_key_secret=settings.alibaba_cloud_access_key_secret.get_secret_value(),
#     )
#     config = oss.Config(
#         region=settings.oss_region,
#         endpoint=settings.oss_endpoint,
#         credentials_provider=credentials,
#     )
#     client = oss.Client(config)
#
# Configuration (environment variables → Settings):
#   OSS_BUCKET_NAME, OSS_ENDPOINT, OSS_REGION, OSS_OBJECT_PREFIX
#
# Factory resolution: src/claimflow/tools/factory.py → get_storage_client()

# ---------------------------------------------------------------------------
# c) Alibaba Cloud RAM (Resource Access Management)
# ---------------------------------------------------------------------------
# API access uses a dedicated RAM user (e.g. ``claimflow-dev``) with minimal
# permissions: DashScope model invocation + OSS bucket read/write on the claims
# prefix only.
#
# Credentials are loaded from environment variables — never hardcoded:
#   ALIBABA_CLOUD_ACCESS_KEY_ID
#   ALIBABA_CLOUD_ACCESS_KEY_SECRET
#   DASHSCOPE_API_KEY          (separate key scoped to DashScope)
#
# Security best practices enforced in this project:
#   - Secrets stored as pydantic ``SecretStr`` (never logged or serialised)
#   - ``.env`` gitignored; ``.env.example`` documents required keys only
#   - RAM user follows least-privilege (no root account keys in application)
#   - Pre-signed OSS URLs with configurable expiry (default 3600 s)
#   - Rotate AccessKeys periodically via Alibaba Cloud console

RAM_DOCUMENTED_USER = "claimflow-dev"


def _build_oss_client(settings: Settings) -> oss.Client:
    """Construct an OSS v2 client using RAM AccessKey credentials."""
    credentials = StaticCredentialsProvider(
        access_key_id=settings.alibaba_cloud_access_key_id.get_secret_value(),
        access_key_secret=settings.alibaba_cloud_access_key_secret.get_secret_value(),
    )
    config = oss.Config(
        region=settings.oss_region,
        endpoint=settings.oss_endpoint,
        credentials_provider=credentials,
    )
    return oss.Client(config)


async def _check_dashscope_connectivity(settings: Settings) -> dict[str, Any]:
    """Probe DashScope OpenAI-compatible API for liveness."""
    endpoint = settings.llm_base_url.rstrip("/")
    api_key = settings.dashscope_api_key.get_secret_value()
    result: dict[str, Any] = {
        "service": "Qwen Cloud (DashScope)",
        "endpoint": endpoint,
        "models_configured": list(QWEN_PRIMARY_MODELS),
        "text_models": list(QWEN_TEXT_MODELS),
        "vision_models": list(QWEN_VISION_MODELS),
    }

    if not api_key:
        result["status"] = "not_configured"
        result["error"] = "DASHSCOPE_API_KEY is empty"
        return result

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{endpoint}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("DashScope connectivity check failed", extra={"error": str(exc)})
        result["status"] = "unreachable"
        result["error"] = str(exc)
        return result

    if response.status_code == 200:
        result["status"] = "connected"
        result["models_available"] = list(QWEN_PRIMARY_MODELS)
        return result

    result["status"] = "error"
    result["http_status"] = response.status_code
    result["error"] = response.text[:200] if response.text else "non-200 response"
    return result


async def _check_oss_connectivity(settings: Settings) -> dict[str, Any]:
    """Report OSS configuration and optionally verify bucket access."""
    result: dict[str, Any] = {
        "service": "Alibaba Cloud OSS",
        "backend": settings.storage_backend,
        "bucket": settings.oss_bucket_name,
        "endpoint": settings.oss_endpoint,
        "region": settings.oss_region,
        "object_prefix": settings.oss_object_prefix,
        "sdk": "alibabacloud-oss-v2",
    }

    if settings.storage_backend == "local":
        # Strategy Pattern: LocalStorage fallback for local development.
        result["status"] = "configured"
        result["note"] = (
            "LocalStorage active (STORAGE_BACKEND=local). "
            "Set STORAGE_BACKEND=oss for production OSS."
        )
        return result

    access_key_id = settings.alibaba_cloud_access_key_id.get_secret_value()
    access_key_secret = settings.alibaba_cloud_access_key_secret.get_secret_value()
    if not access_key_id or not access_key_secret:
        result["status"] = "not_configured"
        result["error"] = "RAM AccessKey credentials are missing"
        return result

    try:
        client = _build_oss_client(settings)
        request = oss.ListObjectsV2Request(
            bucket=settings.oss_bucket_name,
            prefix=settings.oss_object_prefix,
            max_keys=1,
        )
        await asyncio.to_thread(client.list_objects_v2, request)
    except Exception as exc:
        logger.warning("OSS connectivity check failed", extra={"error": str(exc)})
        result["status"] = "error"
        result["error"] = str(exc)
        return result

    result["status"] = "connected"
    return result


def _check_ram_configuration(settings: Settings) -> dict[str, Any]:
    """Verify RAM AccessKey presence without exposing secret values."""
    access_key_id = settings.alibaba_cloud_access_key_id.get_secret_value()
    access_key_secret = settings.alibaba_cloud_access_key_secret.get_secret_value()
    dashscope_key = settings.dashscope_api_key.get_secret_value()

    access_key_set = bool(access_key_id and access_key_secret)
    dashscope_key_set = bool(dashscope_key)

    result: dict[str, Any] = {
        "service": "Alibaba Cloud RAM",
        "documented_ram_user": RAM_DOCUMENTED_USER,
        "access_key_set": access_key_set,
        "dashscope_api_key_set": dashscope_key_set,
        "security": [
            "Secrets loaded from environment variables only",
            "SecretStr prevents accidental logging of credentials",
            "Least-privilege RAM user (no root account keys)",
        ],
    }

    if access_key_set and dashscope_key_set:
        result["status"] = "configured"
    else:
        result["status"] = "not_configured"
        missing: list[str] = []
        if not access_key_set:
            missing.append("ALIBABA_CLOUD_ACCESS_KEY_ID/SECRET")
        if not dashscope_key_set:
            missing.append("DASHSCOPE_API_KEY")
        result["missing"] = missing

    return result


def _derive_overall_status(services: dict[str, dict[str, Any]]) -> str:
    """Map per-service statuses to an aggregate health label."""
    qwen_status = services["qwen_cloud"].get("status", "")
    oss_status = services["oss"].get("status", "")
    ram_status = services["ram"].get("status", "")

    if ram_status != "configured":
        return "unhealthy"

    if qwen_status == "connected":
        if oss_status in {"connected", "configured"}:
            return "healthy"
        return "degraded"

    if qwen_status in {"error", "unreachable"} and oss_status in {"connected", "configured"}:
        return "degraded"

    if qwen_status == "not_configured":
        return "unhealthy"

    return "degraded"


async def verify_alibaba_cloud_connection(
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Test connectivity to Alibaba Cloud services for health checks and hackathon proof.

    Probes:
      - **DashScope** — HTTP GET to ``{llm_base_url}/models`` with API key.
      - **OSS** — ``list_objects_v2`` when ``STORAGE_BACKEND=oss``; reports
        ``configured`` when using LocalStorage fallback.
      - **RAM** — confirms AccessKey and DashScope API key are present (never
        returns secret values).

    Returns:
        Dict with ``status`` (``healthy`` | ``degraded`` | ``unhealthy``) and
        per-service detail under ``alibaba_cloud_services``.

    Example::

        result = await verify_alibaba_cloud_connection()
        # {
        #   "status": "healthy",
        #   "alibaba_cloud_services": {
        #     "qwen_cloud": {"status": "connected", "models_available": [...]},
        #     "oss": {"status": "configured", "backend": "local"},
        #     "ram": {"status": "configured", "access_key_set": True},
        #   },
        # }
    """
    resolved = settings or get_settings()

    qwen_cloud = await _check_dashscope_connectivity(resolved)
    oss_status = await _check_oss_connectivity(resolved)
    ram = _check_ram_configuration(resolved)

    services = {
        "qwen_cloud": qwen_cloud,
        "oss": oss_status,
        "ram": ram,
    }
    overall = _derive_overall_status(services)

    logger.info(
        "Alibaba Cloud connectivity verification completed",
        extra={"overall_status": overall, "qwen": qwen_cloud.get("status"), "oss": oss_status.get("status")},
    )

    return {
        "status": overall,
        "alibaba_cloud_services": services,
    }
