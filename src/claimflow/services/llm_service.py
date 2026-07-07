"""LangChain ChatTongyi clients for Alibaba DashScope with MockLLM offline fallback."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import AIMessage, BaseMessage

from claimflow.core.config import Settings, get_settings
from claimflow.core.logging import get_logger
from claimflow.models.agent_schemas import (
    RiskAssessmentResult,
    TipoDano,
    ToolDecision,
    TriageResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = get_logger(__name__)

T = TypeVar("T")

MOCK_MODEL_NAME = "mock-llm"

_ACCESS_DENIED_MARKERS = (
    "403",
    "accessdenied",
    "unpurchased",
    "permission denied",
    "not authorized",
    "forbidden",
    "model access",
    "invalid model",
    "model not found",
    "insufficient",
)

_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "rate limit",
    "429",
    "503",
    "502",
)


class LLMInvocationError(Exception):
    """Raised when every model in the fallback chain fails (excluding MockLLM)."""

    def __init__(self, message: str, errors: list[str]) -> None:
        super().__init__(message)
        self.errors = errors


def is_model_access_error(exc: BaseException) -> bool:
    """Return True when an exception indicates model permission or purchase issues."""
    message = str(exc).lower()
    return any(marker in message for marker in _ACCESS_DENIED_MARKERS)


def is_transient_llm_error(exc: BaseException) -> bool:
    """Return True for timeouts and other errors worth retrying on a fallback model."""
    if isinstance(exc, TimeoutError):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def _should_try_next_model(exc: BaseException, *, has_more: bool) -> bool:
    """Return True when the fallback chain should continue with the next model."""
    return has_more and (is_model_access_error(exc) or is_transient_llm_error(exc))


def _dedupe_models(models: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _schema_name(schema: type[Any]) -> str:
    return getattr(schema, "__name__", str(schema))


def _extract_message_text(messages: Sequence[BaseMessage | dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(item) for item in content)
    return "\n".join(parts)


def build_mock_structured_output(
    schema: type[Any],
    messages: Sequence[BaseMessage | dict[str, Any]],
) -> Any:
    """Return deterministic structured outputs simulating a fraud investigation scenario."""
    text = _extract_message_text(messages)
    name = _schema_name(schema)

    if schema is TriageResult or name == "TriageResult":
        return TriageResult(
            cliente_nome="João Silva",
            tipo_dano=TipoDano.FOGO,
            localizacao="São Paulo, SP",
            descricao_resumida=(
                "Relato de incêndio após tempestade com chuva forte (resposta mock offline)."
            ),
            data_incidente=datetime(2026, 3, 15),
        )

    if schema is ToolDecision or name == "ToolDecision":
        return ToolDecision(
            requires_tool_call=True,
            tool_name="get_weather_history",
            tool_arguments={"location": "São Paulo, SP", "date": "2026-03-15"},
            reasoning=(
                "Mock offline: relato menciona tempestade/chuva — "
                "verificação climática obrigatória."
            ),
        )

    if schema is RiskAssessmentResult or name == "RiskAssessmentResult":
        justification = (
            "Mock offline: texto relata fogo/tempestade, imagem indica água e clima verificado "
            "como ensolarado — alta probabilidade de inconsistência fraudulenta."
        )
        if "consistência" in text.lower() or "verificação climática" in text.lower():
            justification += " Evidências cruzadas reforçam escalação."
        return RiskAssessmentResult(
            fraud_risk_score=0.88,
            severity_score=0.72,
            justificativa_risco=justification,
            requires_human_review=True,
        )

    raise ValueError(f"MockLLM has no canned response for schema {name}")


class MockStructuredRunnable:
    """Runnable returned by :meth:`MockLLM.with_structured_output`."""

    def __init__(self, schema: type[Any]) -> None:
        self._schema = schema

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage | dict[str, Any]],
        **_kwargs: Any,
    ) -> Any:
        return build_mock_structured_output(self._schema, messages)


class MockLLM:
    """Offline LLM mimicking ChatTongyi structured-output for resilient local development."""

    @property
    def _llm_type(self) -> str:
        return MOCK_MODEL_NAME

    def with_structured_output(self, schema: type[Any]) -> MockStructuredRunnable:
        return MockStructuredRunnable(schema)

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage | dict[str, Any]],
        **_kwargs: Any,
    ) -> AIMessage:
        return AIMessage(content="[MockLLM] offline structured response")


def get_llm_model_chain(settings: Settings | None = None) -> list[str]:
    """Return primary LLM followed by configured fallback models."""
    resolved = settings or get_settings()
    return _dedupe_models([resolved.llm_model_name, *resolved.llm_fallback_models])


def create_chat_llm(
    model: str,
    *,
    temperature: float,
    settings: Settings | None = None,
) -> ChatTongyi:
    """Instantiate a ChatTongyi client for a specific DashScope Qwen model."""
    resolved = settings or get_settings()
    api_key = resolved.dashscope_api_key.get_secret_value()
    os.environ.setdefault("DASHSCOPE_API_KEY", api_key)
    return ChatTongyi(
        model=model,
        api_key=api_key,
        temperature=temperature,
        streaming=False,
    )


def get_triage_llm(settings: Settings | None = None) -> ChatTongyi | MockLLM:
    """Return a low-temperature LLM for triage, falling back to MockLLM on init failure."""
    resolved = settings or get_settings()
    try:
        return create_chat_llm(resolved.llm_model_name, temperature=0.1, settings=resolved)
    except Exception as exc:
        logger.warning(
            "ChatTongyi initialization failed; using MockLLM",
            extra={"error": str(exc), "model": resolved.llm_model_name},
        )
        return MockLLM()


def get_risk_llm(settings: Settings | None = None) -> ChatTongyi | MockLLM:
    """Return an LLM for risk assessment, falling back to MockLLM on init failure."""
    resolved = settings or get_settings()
    try:
        return create_chat_llm(resolved.llm_model_name, temperature=0.3, settings=resolved)
    except Exception as exc:
        logger.warning(
            "ChatTongyi initialization failed; using MockLLM",
            extra={"error": str(exc), "model": resolved.llm_model_name},
        )
        return MockLLM()


async def _invoke_mock_llm(
    messages: list[Any],
    *,
    configure: Callable[[MockLLM], T] | None,
) -> tuple[Any, str]:
    """Invoke MockLLM as the final offline fallback."""
    logger.warning(
        "All DashScope models unavailable; using MockLLM offline fallback",
        extra={"model": MOCK_MODEL_NAME},
    )
    mock = MockLLM()
    runnable: Any = configure(mock) if configure else mock
    result = await runnable.ainvoke(messages)
    return result, MOCK_MODEL_NAME


async def ainvoke_llm_with_fallback(
    messages: list[Any],
    *,
    temperature: float,
    settings: Settings | None = None,
    configure: Callable[[ChatTongyi | MockLLM], T] | None = None,
    preferred_model: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[Any, str]:
    """Invoke ChatTongyi with model fallback, then MockLLM if all models fail."""
    resolved = settings or get_settings()
    models = [preferred_model] if preferred_model else get_llm_model_chain(resolved)
    if preferred_model == MOCK_MODEL_NAME:
        return await _invoke_mock_llm(messages, configure=configure)

    timeout = timeout_seconds if timeout_seconds is not None else resolved.llm_timeout_seconds
    errors: list[str] = []

    for index, model in enumerate(models):
        try:
            llm = create_chat_llm(model, temperature=temperature, settings=resolved)
        except Exception as exc:
            logger.warning(
                "ChatTongyi init failed for model; trying next fallback",
                extra={"model": model, "error": str(exc)},
            )
            errors.append(f"{model}: init {exc}")
            continue

        runnable: Any = configure(llm) if configure else llm
        has_more = index < len(models) - 1
        try:
            result = await asyncio.wait_for(runnable.ainvoke(messages), timeout=timeout)
        except Exception as exc:
            if _should_try_next_model(exc, has_more=has_more):
                logger.warning(
                    "Model call failed; trying next fallback",
                    extra={"model": model, "error": str(exc), "error_type": type(exc).__name__},
                )
                errors.append(f"{model}: {exc}")
                continue
            if is_model_access_error(exc) or is_transient_llm_error(exc):
                errors.append(f"{model}: {exc}")
                break
            raise

        if index > 0:
            logger.warning(
                f"Falling back to {model} due to access restrictions",
                extra={"model": model, "failed_models": errors},
            )
        logger.info(
            "LLM invocation succeeded",
            extra={"model": model, "provider": "chat-tongyi", "used_fallback": index > 0},
        )
        return result, model

    return await _invoke_mock_llm(messages, configure=configure)
