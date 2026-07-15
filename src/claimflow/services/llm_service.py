"""LangChain ChatTongyi clients for Alibaba DashScope with MockLLM offline fallback."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import AIMessage, BaseMessage

from claimflow.core.config import Settings, get_settings
from claimflow.core.i18n import get_request_language, normalize_language
from claimflow.core.logging import get_logger
from claimflow.models.agent_schemas import (
    RiskAssessmentResult,
    TipoDano,
    ToolDecision,
    TriageResult,
)
from claimflow.services.mock_scenarios import (
    MockScenario,
    detect_mock_scenario,
    get_mock_scenario_payload,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = get_logger(__name__)

T = TypeVar("T")

MOCK_MODEL_NAME = "mock-llm"

MOCK_MODE_INFO_MESSAGE = (
    "🎭 MOCK MODE: Using deterministic scenarios for demo "
    "(DashScope models not available in this account tier)"
)

# Legacy alias kept for backward-compatible log filters.
MOCK_SCENARIO_FRAUD_DETECTION = "FRAUD_CLAIM"

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "pt": "Portuguese",
    "es": "Spanish",
}

TRIAGE_SYSTEM_PROMPT = """\
You are ClaimFlow, a senior insurance claims triage AI.

CRITICAL LANGUAGE RULE: You MUST respond in {language_name}. All field values \
in your JSON output must be in this language.

Your task: Extract structured data from customer claim descriptions.

OUTPUT FORMAT: Return JSON matching the TriageResult schema exactly.
- cliente_nome: customer's full name (preserve original language)
- tipo_dano: one of AGUA, FOGO, VENTO, OUTRO
- localizacao: city/region mentioned
- descricao_resumida: brief summary in {language_name}
- data_incidente: ISO date if mentioned, else null

Be precise. Extract only what is explicitly stated. Do not invent information.
"""

INVESTIGATION_SYSTEM_PROMPT = """\
You are ClaimFlow, a senior insurance claims investigator.

CRITICAL LANGUAGE RULE: You MUST respond in {language_name}. All free-text \
fields (especially reasoning) must be in this language.

Your task: Decide whether external weather verification is required.

Rules:
- If the report mentions weather events (rain, wind, storm, hail) AND provides \
a location and date, you MUST call 'get_weather_history'.
- Set requires_tool_call=True, tool_name='get_weather_history', and \
tool_arguments={{"location": "...", "date": "..."}}.
- Otherwise return requires_tool_call=False, tool_name='none', tool_arguments={{}}.
- Explain your decision in reasoning (in {language_name}).
- Keep enum/tool identifiers unchanged.

Be precise. Do not invent locations or dates that are not in the claim text.
"""

RISK_SYSTEM_PROMPT = """\
You are ClaimFlow, a senior insurance fraud analyst. Be sceptical and evidence-based.

CRITICAL LANGUAGE RULE: You MUST respond in {language_name}. All free-text \
fields (especially justificativa_risco) must be in this language.

Your task: Assess fraud risk and severity for the structured claim.

Guidelines:
- Look for inconsistencies, exaggerations, omissions, and fraud patterns.
- Consider visual analysis and text-image consistency when provided.
- Consider weather verification when provided.
- fraud_risk_score: probability of fraudulent intent (0.0 = none, 1.0 = extremely high).
- severity_score: estimated financial/operational impact \
(0.0 = trivial, 1.0 = catastrophic).
- justificativa_risco: explain score drivers in {language_name}.
- requires_human_review: true if any material doubt needs a human adjuster.
- Do not approve claims; your job is risk assessment only.

Be precise. Base conclusions only on provided evidence.
"""


def get_triage_system_prompt(language: str = "en") -> str:
    """Build the triage system prompt forcing output in the selected language.

    Defaults to English for the Alibaba Cloud hackathon.
    """
    language_name = _LANGUAGE_NAMES.get(normalize_language(language), "English")
    return TRIAGE_SYSTEM_PROMPT.format(language_name=language_name)


def get_investigation_system_prompt(language: str = "en") -> str:
    """Build the investigation system prompt forcing output in the selected language."""
    language_name = _LANGUAGE_NAMES.get(normalize_language(language), "English")
    return INVESTIGATION_SYSTEM_PROMPT.format(language_name=language_name)


def get_risk_system_prompt(language: str = "en") -> str:
    """Build the risk-assessment system prompt forcing output in the selected language."""
    language_name = _LANGUAGE_NAMES.get(normalize_language(language), "English")
    return RISK_SYSTEM_PROMPT.format(language_name=language_name)

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


def log_mock_llm_scenario_selection(raw_input: str, *, claim_id: str | None = None) -> None:
    """Log scenario detection once per claim for transparent demo mode."""
    scenario, keyword = detect_mock_scenario(raw_input)
    keyword_detail = f" (keyword: '{keyword}')" if keyword else " (default — no keywords)"
    resolved_id = claim_id or "pending"
    logger.info(
        f"🎭 MockLLM: Detected scenario {scenario.value}{keyword_detail}",
        extra={
            "mock_scenario": scenario.value,
            "mock_keyword": keyword,
            "claim_id": resolved_id,
            "model": MOCK_MODEL_NAME,
        },
    )
    logger.info(
        "🎭 MockLLM: Returning deterministic response for demo consistency",
        extra={"mock_scenario": scenario.value, "claim_id": resolved_id},
    )


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


def _parse_incident_date(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _build_triage_from_payload(payload: dict[str, Any]) -> TriageResult:
    return TriageResult(
        cliente_nome=str(payload["cliente_nome"]),
        tipo_dano=TipoDano(str(payload["tipo_dano"])),
        localizacao=str(payload["localizacao"]),
        descricao_resumida=str(payload["descricao_resumida"]),
        data_incidente=_parse_incident_date(payload.get("data_incidente")),
    )


def _build_tool_from_payload(payload: dict[str, Any]) -> ToolDecision:
    return ToolDecision(
        requires_tool_call=bool(payload["requires_tool_call"]),
        tool_name=payload["tool_name"],  # type: ignore[arg-type]
        tool_arguments=dict(payload.get("tool_arguments") or {}),
        reasoning=str(payload["tool_reasoning"]),
    )


def _build_risk_from_payload(payload: dict[str, Any]) -> RiskAssessmentResult:
    return RiskAssessmentResult(
        fraud_risk_score=float(payload["fraud_risk_score"]),
        severity_score=float(payload["severity_score"]),
        justificativa_risco=str(payload["justificativa_risco"]),
        requires_human_review=bool(payload["requires_human_review"]),
    )


def _build_storm_triage() -> TriageResult:
    return _build_triage_from_payload(
        get_mock_scenario_payload(MockScenario.STORM_CLAIM, get_request_language())
    )


def _build_fraud_triage() -> TriageResult:
    return _build_triage_from_payload(
        get_mock_scenario_payload(MockScenario.FRAUD_CLAIM, get_request_language())
    )


def _build_ambiguous_triage() -> TriageResult:
    return _build_triage_from_payload(
        get_mock_scenario_payload(MockScenario.AMBIGUOUS, get_request_language())
    )


def _build_storm_tool_decision() -> ToolDecision:
    return _build_tool_from_payload(
        get_mock_scenario_payload(MockScenario.STORM_CLAIM, get_request_language())
    )


def _build_fraud_tool_decision() -> ToolDecision:
    return _build_tool_from_payload(
        get_mock_scenario_payload(MockScenario.FRAUD_CLAIM, get_request_language())
    )


def _build_ambiguous_tool_decision() -> ToolDecision:
    return _build_tool_from_payload(
        get_mock_scenario_payload(MockScenario.AMBIGUOUS, get_request_language())
    )


def _build_storm_risk() -> RiskAssessmentResult:
    return _build_risk_from_payload(
        get_mock_scenario_payload(MockScenario.STORM_CLAIM, get_request_language())
    )


def _build_fraud_risk() -> RiskAssessmentResult:
    return _build_risk_from_payload(
        get_mock_scenario_payload(MockScenario.FRAUD_CLAIM, get_request_language())
    )


def _build_ambiguous_risk() -> RiskAssessmentResult:
    return _build_risk_from_payload(
        get_mock_scenario_payload(MockScenario.AMBIGUOUS, get_request_language())
    )


def build_mock_structured_output(
    schema: type[Any],
    messages: Sequence[BaseMessage | dict[str, Any]],
) -> Any:
    """Return deterministic structured outputs for hackathon demo scenarios."""
    text = _extract_message_text(messages)
    scenario, _keyword = detect_mock_scenario(text)
    name = _schema_name(schema)

    if schema is TriageResult or name == "TriageResult":
        if scenario is MockScenario.STORM_CLAIM:
            return _build_storm_triage()
        if scenario is MockScenario.FRAUD_CLAIM:
            return _build_fraud_triage()
        return _build_ambiguous_triage()

    if schema is ToolDecision or name == "ToolDecision":
        if scenario is MockScenario.STORM_CLAIM:
            return _build_storm_tool_decision()
        if scenario is MockScenario.FRAUD_CLAIM:
            return _build_fraud_tool_decision()
        return _build_ambiguous_tool_decision()

    if schema is RiskAssessmentResult or name == "RiskAssessmentResult":
        if scenario is MockScenario.STORM_CLAIM:
            return _build_storm_risk()
        if scenario is MockScenario.FRAUD_CLAIM:
            return _build_fraud_risk()
        return _build_ambiguous_risk()

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


def _log_mock_llm_usage(
    *,
    claim_id: str | None = None,
    raw_input: str | None = None,
) -> None:
    """Emit clear INFO logs when MockLLM serves a request."""
    logger.info(MOCK_MODE_INFO_MESSAGE)
    scenario, keyword = detect_mock_scenario(raw_input or "")
    keyword_detail = f" (keyword: '{keyword}')" if keyword else ""
    resolved_id = claim_id or "pending"
    logger.info(
        f"🎭 MockLLM scenario: {scenario.value}{keyword_detail} (claim_id={resolved_id})",
        extra={
            "mock_scenario": scenario.value,
            "mock_keyword": keyword,
            "claim_id": resolved_id,
            "model": MOCK_MODEL_NAME,
        },
    )


def get_triage_llm(settings: Settings | None = None) -> ChatTongyi | MockLLM:
    """Return a low-temperature LLM for triage, falling back to MockLLM on init failure."""
    resolved = settings or get_settings()
    if resolved.use_mock_llm:
        _log_mock_llm_usage()
        return MockLLM()
    try:
        return create_chat_llm(resolved.llm_model_name, temperature=0.1, settings=resolved)
    except Exception as exc:
        logger.warning(
            "ChatTongyi initialization failed; using MockLLM",
            extra={"error": str(exc), "model": resolved.llm_model_name},
        )
        _log_mock_llm_usage()
        return MockLLM()


def get_risk_llm(settings: Settings | None = None) -> ChatTongyi | MockLLM:
    """Return an LLM for risk assessment, falling back to MockLLM on init failure."""
    resolved = settings or get_settings()
    if resolved.use_mock_llm:
        _log_mock_llm_usage()
        return MockLLM()
    try:
        return create_chat_llm(resolved.llm_model_name, temperature=0.3, settings=resolved)
    except Exception as exc:
        logger.warning(
            "ChatTongyi initialization failed; using MockLLM",
            extra={"error": str(exc), "model": resolved.llm_model_name},
        )
        _log_mock_llm_usage()
        return MockLLM()


async def _invoke_mock_llm(
    messages: list[Any],
    *,
    configure: Callable[[MockLLM], T] | None,
    claim_id: str | None = None,
    configured_mode: bool = False,
) -> tuple[Any, str]:
    """Invoke MockLLM as the final offline fallback or when ``USE_MOCK_LLM=true``."""
    if not configured_mode:
        logger.warning(
            "All DashScope models unavailable; using MockLLM offline fallback",
            extra={"model": MOCK_MODEL_NAME},
        )
    raw_input = _extract_message_text(messages)
    _log_mock_llm_usage(claim_id=claim_id, raw_input=raw_input)
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
    claim_id: str | None = None,
) -> tuple[Any, str]:
    """Invoke ChatTongyi with model fallback, then MockLLM if all models fail."""
    resolved = settings or get_settings()
    if resolved.use_mock_llm:
        return await _invoke_mock_llm(
            messages,
            configure=configure,
            claim_id=claim_id,
            configured_mode=True,
        )

    models = [preferred_model] if preferred_model else get_llm_model_chain(resolved)
    if preferred_model == MOCK_MODEL_NAME:
        return await _invoke_mock_llm(messages, configure=configure, claim_id=claim_id)

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

    return await _invoke_mock_llm(messages, configure=configure, claim_id=claim_id)
