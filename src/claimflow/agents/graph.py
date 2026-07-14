"""LangGraph StateGraph for claim processing with DashScope/Qwen structured output."""

import json
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from claimflow.agents.states import ClaimAgentState, ClaimStatus
from claimflow.core.config import get_settings
from claimflow.core.context import bind_claim_correlation
from claimflow.core.logging import get_logger
from claimflow.models.agent_schemas import RiskAssessmentResult, ToolDecision, TriageResult
from claimflow.services.llm_service import (
    MOCK_MODEL_NAME,
    LLMInvocationError,
    ainvoke_llm_with_fallback,
    log_mock_llm_scenario_selection,
)
from claimflow.services.vision_service import VisionService, VisionServiceError
from claimflow.tools.weather_tool import get_weather_history

logger = get_logger(__name__)

# Below this consistency score a text-image mismatch is considered severe fraud signal.
SEVERE_INCONSISTENCY_THRESHOLD: float = 0.3
# Fraud score applied when text and image report incompatible damage types.
SEVERE_INCONSISTENCY_FRAUD_SCORE: float = 0.85

TRIAGE_SYSTEM_PROMPT = """\
Você é um assistente especializado em sinistros de seguros residenciais no Brasil.
Sua tarefa é extrair informações estruturadas do texto bruto de um aviso de sinistro.

Regras:
- Extraia apenas informações explicitamente presentes ou claramente inferíveis do texto.
- Se um campo não puder ser determinado, use valores razoáveis e indique incerteza na descrição.
- Classifique o tipo de dano (AGUA, FOGO, VENTO, OUTRO) com base no relato.
- A descrição resumida deve ter no máximo 3 frases em português brasileiro.
- Para data_incidente, retorne null se a data não for mencionada.
"""

INVESTIGATION_SYSTEM_PROMPT = """\
Você é um investigador de sinistros de seguros residenciais no Brasil.
Analise o relato do cliente e decida se é necessária verificação climática externa.

Regras:
- Analise o relato do cliente. Se ele mencionar eventos climáticos (chuva, vento, \
tempestade, granizo, vendaval) e fornecer uma localização e data, você DEVE decidir \
chamar a ferramenta 'get_weather_history'.
- Nesse caso, defina requires_tool_call=True, tool_name='get_weather_history' e preencha \
tool_arguments com {"location": "...", "date": "..."} extraídos do texto.
- Caso contrário, retorne requires_tool_call=False, tool_name='none' e tool_arguments={}.
- Explique sua decisão em reasoning.
- Use formatos razoáveis para local e data (ex.: "São Paulo, SP", "2026-03-15" ou "ontem").
"""

RISK_SYSTEM_PROMPT = """\
Você é um analista sênior de fraudes em sinistros de seguros, com postura cética \
e baseada em evidências.
Avalie o sinistro estruturado abaixo e atribua scores de risco de fraude e severidade.

Diretrizes:
- Seja cético: procure inconsistências, exageros, omissões e padrões típicos de fraude.
- Considere a análise visual (se fornecida) e o score de consistência texto-imagem.
- Considere a verificação climática (se fornecida) ao avaliar coerência do relato.
- fraud_risk_score: probabilidade de intenção fraudulenta (0.0 = sem indícios, 1.0 = altíssima).
- severity_score: impacto financeiro/operacional estimado (0.0 = trivial, 1.0 = catastrófico).
- justificativa_risco: explique os fatores que influenciaram os scores (em português).
- requires_human_review: true se houver qualquer dúvida material que exija um perito humano.
- Não aprove sinistros automaticamente; sua função é apenas avaliar risco.
"""


FAIL_CLOSED_REASON = "Insufficient data extracted from claim"
MISSING_IMAGE_ANALYSIS_PENALTY = 0.3
MISSING_WEATHER_VERIFICATION_PENALTY = 0.2
MIN_FRAUD_ON_DATA_GAP = 0.01

_WEATHER_KEYWORDS: tuple[str, ...] = (
    "chuva",
    "vento",
    "tempestade",
    "granizo",
    "vendaval",
    "rajada",
    "inundação",
    "inundacao",
    "alagamento",
    "storm",
    "rain",
    "hurricane",
    "tornado",
    "climát",
    "climatic",
    "weather",
    "enchente",
    "nevasca",
    "geada",
)


def _mentions_weather_climate(text: str) -> bool:
    """Return True when the claim text references weather or climate events."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in _WEATHER_KEYWORDS)


def _weather_verification_unavailable(weather_verification: object | None) -> bool:
    """Return True when weather evidence is missing or an Open-Meteo error dict."""
    if not weather_verification:
        return True
    return bool(isinstance(weather_verification, dict) and weather_verification.get("error"))


def _compute_fail_closed_penalties(state: ClaimAgentState) -> tuple[float, list[str]]:
    """Apply additive fraud penalties when expected evidence is missing."""
    penalties: list[str] = []
    bonus = 0.0

    if state.get("image_path") and not state.get("image_analysis"):
        bonus += MISSING_IMAGE_ANALYSIS_PENALTY
        penalties.append("Image provided but visual analysis unavailable (+0.3)")

    raw_input = state.get("raw_input", "")
    if _mentions_weather_climate(raw_input) and _weather_verification_unavailable(
        state.get("weather_verification")
    ):
        bonus += MISSING_WEATHER_VERIFICATION_PENALTY
        penalties.append("Weather mentioned but verification unavailable (+0.2)")

    return bonus, penalties


def _has_data_integrity_gaps(state: ClaimAgentState, fail_closed_penalties: list[str]) -> bool:
    """Detect states that must never auto-approve with a zero fraud score."""
    extracted_data = state.get("extracted_data") or {}
    return bool(
        state.get("system_error")
        or state.get("error")
        or not extracted_data
        or fail_closed_penalties
    )


def _system_error_state(state: ClaimAgentState, node: str, message: str) -> ClaimAgentState:
    """Build a partial state update for irrecoverable LLM/vision failures."""
    claim_id = state["claim_id"]
    logger.error(
        "FAIL-CLOSED: Escalating to human review due to missing data",
        extra={"claim_id": claim_id, "node": node, "error_message": message},
    )
    return {
        **state,
        "status": ClaimStatus.HUMAN_REVIEW,
        "system_error": True,
        "requires_human_review": True,
        "fraud_risk_score": max(state.get("fraud_risk_score", 0.0), 1.0),
        "severity_score": max(state.get("severity_score", 0.0), 1.0),
        "risk_score": 1.0,
        "error": message,
        "error_message": message,
    }


def _wrap_safe_node(
    node_name: str,
    node_fn: Callable[[ClaimAgentState], Awaitable[ClaimAgentState]],
) -> Callable[[ClaimAgentState], Awaitable[ClaimAgentState]]:
    """Catch unhandled exceptions and log per-node processing time."""

    async def safe_node(state: ClaimAgentState) -> ClaimAgentState:
        claim_id = state.get("claim_id")
        if claim_id:
            bind_claim_correlation(str(claim_id))

        started = time.perf_counter()
        try:
            try:
                return await node_fn(state)
            except Exception as exc:
                logger.critical(
                    "Unhandled exception in graph node",
                    extra={
                        "claim_id": claim_id,
                        "node": node_name,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                return _system_error_state(state, node_name, f"{node_name} failed: {exc}")
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "Graph node processing time",
                extra={
                    "claim_id": claim_id,
                    "node": node_name,
                    "duration_ms": duration_ms,
                },
            )

    safe_node.__name__ = node_fn.__name__
    return safe_node


def _composite_risk_score(fraud: float, severity: float) -> float:
    """Return the composite risk score used for routing and API responses."""
    return max(fraud, severity)


def _resolve_status(
    fraud_score: float,
    severity_score: float,
    requires_human_review: bool,
) -> ClaimStatus:
    """Map LLM scores to a final claim status using configured thresholds."""
    settings = get_settings()
    composite = _composite_risk_score(fraud_score, severity_score)

    if composite >= settings.reject_threshold:
        return ClaimStatus.REJECTED
    if requires_human_review or composite >= settings.risk_threshold:
        return ClaimStatus.HUMAN_REVIEW
    return ClaimStatus.APPROVED


async def _run_vision_cross_validation(
    state: ClaimAgentState,
    triage_result: TriageResult,
) -> dict:
    """Analyse the claim image and compute text-vs-image consistency."""
    claim_id = state["claim_id"]
    image_path = state.get("image_path")
    updates: dict = {
        "image_analysis": None,
        "consistency_score": None,
        "fraud_risk_score": state.get("fraud_risk_score", 0.0),
    }

    if not image_path:
        return updates

    vision = VisionService()

    try:
        image_analysis = await vision.analyze_claim_image(image_path, state["raw_input"])
    except VisionServiceError as exc:
        logger.error(
            "Vision analysis failed; escalating fraud signal",
            extra={"claim_id": claim_id, "node": "triage", "error": str(exc)},
        )
        updates["error"] = f"Vision analysis failed: {exc}"
        updates["error_message"] = updates["error"]
        updates["fraud_risk_score"] = max(state.get("fraud_risk_score", 0.0), 0.7)
        return updates

    text_damage = triage_result.tipo_dano.value
    image_damage = str(image_analysis.get("detected_damage_type", "OUTRO"))
    consistency = VisionService.compute_consistency_score(text_damage, image_damage)

    logger.info(
        "Text-image cross-validation completed",
        extra={
            "claim_id": claim_id,
            "node": "triage",
            "text_damage_type": text_damage,
            "image_damage_type": image_damage,
            "consistency_score": consistency,
            "consistency_pct": round(consistency * 100, 1),
        },
    )

    updates["image_analysis"] = image_analysis
    updates["consistency_score"] = consistency

    inconsistencies = image_analysis.get("inconsistencies") or []
    if consistency < SEVERE_INCONSISTENCY_THRESHOLD or inconsistencies:
        logger.warning(
            "Severe text-image inconsistency detected",
            extra={
                "claim_id": claim_id,
                "node": "triage",
                "text_says": text_damage,
                "image_shows": image_damage,
                "consistency_pct": round(consistency * 100, 1),
                "inconsistencies": inconsistencies,
            },
        )
        updates["fraud_risk_score"] = SEVERE_INCONSISTENCY_FRAUD_SCORE

    return updates


async def triage_node(state: ClaimAgentState) -> ClaimAgentState:
    """Extract structured claim fields and optionally cross-validate with Qwen-VL."""
    claim_id = state["claim_id"]
    log = logger
    log.info("Triage node started", extra={"claim_id": claim_id, "node": "triage"})

    messages = [
        SystemMessage(content=TRIAGE_SYSTEM_PROMPT),
        HumanMessage(content=state["raw_input"]),
    ]

    try:
        triage_result, model = await ainvoke_llm_with_fallback(
            messages,
            temperature=0.1,
            configure=lambda llm: llm.with_structured_output(TriageResult),
            claim_id=claim_id,
        )
        if model == MOCK_MODEL_NAME:
            log_mock_llm_scenario_selection(state["raw_input"], claim_id=claim_id)
    except LLMInvocationError as exc:
        return _system_error_state(state, "triage", f"Triage failed: {exc}")
    except Exception as exc:
        log.error(
            "Triage structured output failed",
            extra={"claim_id": claim_id, "node": "triage", "error": str(exc)},
        )
        return _system_error_state(state, "triage", f"Triage failed: {exc}")

    extracted = triage_result.model_dump(mode="json")
    vision_updates = await _run_vision_cross_validation(state, triage_result)

    if vision_updates.get("system_error"):
        return {
            **state,
            "extracted_data": extracted,
            "image_analysis": vision_updates.get("image_analysis"),
            "consistency_score": vision_updates.get("consistency_score"),
            "fraud_risk_score": vision_updates.get("fraud_risk_score", 0.0),
            "status": ClaimStatus.HUMAN_REVIEW,
            "system_error": True,
            "requires_human_review": True,
            "error": vision_updates.get("error", ""),
            "error_message": vision_updates.get("error_message", ""),
        }

    log.info(
        "Triage completed",
        extra={
            "claim_id": claim_id,
            "node": "triage",
            "tipo_dano": triage_result.tipo_dano,
            "has_image": bool(state.get("image_path")),
            "consistency_score": vision_updates.get("consistency_score"),
        },
    )

    return {
        **state,
        "extracted_data": extracted,
        "image_analysis": vision_updates.get("image_analysis"),
        "consistency_score": vision_updates.get("consistency_score"),
        "fraud_risk_score": vision_updates.get("fraud_risk_score", 0.0),
        "status": ClaimStatus.PENDING,
        "error": vision_updates.get("error", state.get("error", "")),
    }


async def _invoke_weather_tool(tool_arguments: dict) -> dict:
    """Call get_weather_history with validated arguments from ToolDecision."""
    location = str(tool_arguments.get("location", "")).strip()
    date = str(tool_arguments.get("date", "")).strip()
    if not location or not date:
        raise ValueError("tool_arguments must include non-empty 'location' and 'date'")
    return await get_weather_history(location, date)


async def investigation_node(state: ClaimAgentState) -> ClaimAgentState:
    """Investigate external evidence via structured ToolDecision + direct Python calls.

    The LLM returns a :class:`ToolDecision` (JSON mode). When ``requires_tool_call`` is
    True, this node invokes :func:`get_weather_history` directly — no LangChain bind_tools.
    """
    claim_id = state["claim_id"]
    log = logger
    log.info("Investigation node started", extra={"claim_id": claim_id, "node": "investigation"})

    if state.get("system_error"):
        return state

    messages = [
        SystemMessage(content=INVESTIGATION_SYSTEM_PROMPT),
        HumanMessage(content=state["raw_input"]),
    ]

    tool_calls_made: list[str] = list(state.get("tool_calls_made") or [])
    weather_verification = state.get("weather_verification")

    try:
        tool_decision, model = await ainvoke_llm_with_fallback(
            messages,
            temperature=0.1,
            configure=lambda llm: llm.with_structured_output(ToolDecision),
            claim_id=claim_id,
        )
    except LLMInvocationError as exc:
        return _system_error_state(state, "investigation", f"Investigation failed: {exc}")
    except Exception as exc:
        return _system_error_state(state, "investigation", f"Investigation failed: {exc}")

    log.info(
        "Tool decision received",
        extra={
            "claim_id": claim_id,
            "node": "investigation",
            "requires_tool_call": tool_decision.requires_tool_call,
            "tool_name": tool_decision.tool_name,
            "reasoning": tool_decision.reasoning,
            "model": model,
        },
    )

    if tool_decision.requires_tool_call and tool_decision.tool_name == "get_weather_history":
        try:
            weather_verification = await _invoke_weather_tool(tool_decision.tool_arguments)
            tool_calls_made.append("get_weather_history")
        except Exception as exc:
            log.error(
                "Weather tool execution failed",
                extra={"claim_id": claim_id, "node": "investigation", "error": str(exc)},
            )
            return _system_error_state(
                state,
                "investigation",
                f"Weather tool execution failed: {exc}",
            )

    log.info(
        "Investigation completed",
        extra={
            "claim_id": claim_id,
            "node": "investigation",
            "tool_calls_made": tool_calls_made,
            "has_weather_verification": weather_verification is not None,
            "model": model,
        },
    )

    return {
        **state,
        "weather_verification": weather_verification,
        "tool_calls_made": tool_calls_made,
    }


async def risk_assessment_node(state: ClaimAgentState) -> ClaimAgentState:
    """Assess fraud risk and severity from triage + vision data using a sceptical LLM."""
    claim_id = state["claim_id"]
    log = logger
    log.info(
        "Risk assessment node started",
        extra={"claim_id": claim_id, "node": "risk_assessment"},
    )

    if state.get("system_error"):
        return {
            **state,
            "status": ClaimStatus.HUMAN_REVIEW,
            "requires_human_review": True,
            "fraud_risk_score": max(state.get("fraud_risk_score", 0.0), 1.0),
            "severity_score": max(state.get("severity_score", 0.0), 1.0),
            "risk_score": 1.0,
        }

    pre_triage_fraud = state.get("fraud_risk_score", 0.0)
    extracted_data = state.get("extracted_data") or {}
    fail_closed_bonus, fail_closed_penalties = _compute_fail_closed_penalties(state)

    if not extracted_data:
        logger.warning(
            "FAIL-CLOSED: Escalating to human review due to missing data",
            extra={
                "claim_id": claim_id,
                "node": "risk_assessment",
                "reason": FAIL_CLOSED_REASON,
            },
        )
        return {
            **state,
            "fraud_risk_score": max(pre_triage_fraud, 1.0),
            "severity_score": 1.0,
            "risk_score": 1.0,
            "requires_human_review": True,
            "risk_assessment": {
                "fraud_risk_score": 1.0,
                "severity_score": 1.0,
                "justificativa_risco": FAIL_CLOSED_REASON,
                "requires_human_review": True,
                "fail_closed_reason": FAIL_CLOSED_REASON,
                "fail_closed_penalties": fail_closed_penalties,
            },
            "status": ClaimStatus.HUMAN_REVIEW,
            "error": FAIL_CLOSED_REASON,
            "error_message": FAIL_CLOSED_REASON,
        }

    context_parts = [
        f"Dados do sinistro (claim_id={claim_id}):\n",
        json.dumps(extracted_data, ensure_ascii=False, indent=2),
    ]
    if state.get("image_analysis"):
        context_parts.append(
            "\nAnálise visual (Qwen-VL):\n"
            + json.dumps(state["image_analysis"], ensure_ascii=False, indent=2)
        )
    if state.get("consistency_score") is not None:
        score = state["consistency_score"]
        context_parts.append(f"\nScore de consistência texto-imagem: {score:.2f}")
    if state.get("weather_verification"):
        context_parts.append(
            "\nVerificação climática:\n"
            + json.dumps(state["weather_verification"], ensure_ascii=False, indent=2)
        )
    if pre_triage_fraud > 0:
        context_parts.append(
            f"\nFraud score pré-triage (inconsistência visual): {pre_triage_fraud:.2f}"
        )

    triage_payload = "".join(context_parts)
    messages = [
        SystemMessage(content=RISK_SYSTEM_PROMPT),
        HumanMessage(content=triage_payload),
    ]

    try:
        risk_result, _model = await ainvoke_llm_with_fallback(
            messages,
            temperature=0.3,
            configure=lambda llm: llm.with_structured_output(RiskAssessmentResult),
            claim_id=claim_id,
        )
    except LLMInvocationError as exc:
        return _system_error_state(state, "risk_assessment", f"Risk assessment failed: {exc}")
    except Exception as exc:
        return _system_error_state(state, "risk_assessment", f"Risk assessment failed: {exc}")

    merged_fraud = min(max(pre_triage_fraud, risk_result.fraud_risk_score) + fail_closed_bonus, 1.0)
    if _has_data_integrity_gaps(state, fail_closed_penalties):
        merged_fraud = max(merged_fraud, MIN_FRAUD_ON_DATA_GAP)
        if fail_closed_penalties:
            logger.warning(
                "FAIL-CLOSED: Escalating to human review due to missing data",
                extra={
                    "claim_id": claim_id,
                    "node": "risk_assessment",
                    "penalties": fail_closed_penalties,
                    "fraud_risk_score": merged_fraud,
                },
            )

    requires_review = (
        risk_result.requires_human_review
        or bool(fail_closed_penalties)
        or (
            state.get("consistency_score") is not None
            and state["consistency_score"] < SEVERE_INCONSISTENCY_THRESHOLD
        )
    )

    risk_payload = risk_result.model_dump(mode="json")
    if fail_closed_penalties:
        risk_payload["fail_closed_penalties"] = fail_closed_penalties
        existing = risk_payload.get("justificativa_risco", "")
        penalty_note = "; ".join(fail_closed_penalties)
        risk_payload["justificativa_risco"] = (
            f"{existing} | FAIL-CLOSED penalties: {penalty_note}"
            if existing
            else f"FAIL-CLOSED penalties: {penalty_note}"
        )

    final_status = _resolve_status(merged_fraud, risk_result.severity_score, requires_review)
    composite = _composite_risk_score(merged_fraud, risk_result.severity_score)

    log.info(
        "Risk assessment completed",
        extra={
            "claim_id": claim_id,
            "node": "risk_assessment",
            "fraud_risk_score": merged_fraud,
            "severity_score": risk_result.severity_score,
            "composite_score": composite,
            "final_status": final_status,
            "pre_triage_fraud": pre_triage_fraud,
        },
    )

    return {
        **state,
        "fraud_risk_score": merged_fraud,
        "severity_score": risk_result.severity_score,
        "risk_score": composite,
        "requires_human_review": requires_review,
        "risk_assessment": risk_payload,
        "status": final_status,
    }


async def human_review_node(state: ClaimAgentState) -> ClaimAgentState:
    """Apply a human decision after LangGraph resumes past ``interrupt_before``.

    The graph pauses *before* this node. The review API writes ``human_decision``
    via ``update_state`` and then resumes; this node finalises the claim status.
    """
    claim_id = state["claim_id"]
    raw_decision = state.get("human_decision")
    decision_value = None
    if isinstance(raw_decision, str):
        decision_value = raw_decision.strip().upper()
    elif isinstance(raw_decision, ClaimStatus):
        decision_value = raw_decision.value

    if decision_value in {ClaimStatus.APPROVED.value, ClaimStatus.REJECTED.value}:
        final_status = ClaimStatus(decision_value)
        logger.info(
            "Human decision applied after LangGraph resume",
            extra={
                "claim_id": claim_id,
                "node": "human_review",
                "status": final_status,
                "analyst_id": state.get("analyst_id"),
                "system_error": state.get("system_error", False),
            },
        )
        return {
            **state,
            "status": final_status,
            "awaiting_human_decision": False,
            "graph_interrupted": False,
            "requires_human_review": False,
        }

    logger.info(
        "Claim still awaiting human decision at human_review node",
        extra={
            "claim_id": claim_id,
            "node": "human_review",
            "status": ClaimStatus.HUMAN_REVIEW,
            "system_error": state.get("system_error", False),
        },
    )
    return {
        **state,
        "status": ClaimStatus.HUMAN_REVIEW,
        "awaiting_human_decision": True,
        "graph_interrupted": True,
    }


async def approval_node(state: ClaimAgentState) -> ClaimAgentState:
    """Confirm automated approval for low-risk claims."""
    claim_id = state["claim_id"]
    logger.info(
        "Claim auto-approved",
        extra={"claim_id": claim_id, "node": "approval", "status": ClaimStatus.APPROVED},
    )
    return {**state, "status": ClaimStatus.APPROVED}


async def rejected_node(state: ClaimAgentState) -> ClaimAgentState:
    """Confirm rejection for high-risk or likely-fraudulent claims."""
    claim_id = state["claim_id"]
    logger.info(
        "Claim rejected",
        extra={"claim_id": claim_id, "node": "rejected", "status": ClaimStatus.REJECTED},
    )
    return {**state, "status": ClaimStatus.REJECTED}


def route_after_investigation(
    state: ClaimAgentState,
) -> Literal["risk_assessment", "human_review"]:
    """Skip risk assessment when a prior node flagged a system error."""
    if state.get("system_error"):
        return "human_review"
    return "risk_assessment"


def route_after_risk_assessment(
    state: ClaimAgentState,
) -> Literal["human_review", "approval", "rejected"]:
    """Route claims based on the status resolved during risk assessment."""
    status = state.get("status", ClaimStatus.HUMAN_REVIEW)

    if status == ClaimStatus.REJECTED:
        return "rejected"
    if status == ClaimStatus.HUMAN_REVIEW:
        return "human_review"
    return "approval"


HUMAN_REVIEW_NODE = "human_review"


def thread_config(claim_id: str) -> dict[str, dict[str, str]]:
    """Build the LangGraph runnable config keyed by ``claim_id`` as ``thread_id``."""
    return {"configurable": {"thread_id": claim_id}}


async def is_awaiting_human_review(
    graph: CompiledStateGraph,
    claim_id: str,
) -> bool:
    """Return True when the checkpoint is paused before ``human_review``."""
    try:
        snapshot = await graph.aget_state(thread_config(claim_id))
    except Exception:  # noqa: BLE001 — missing thread / checkpointer
        return False
    next_nodes = snapshot.next or ()
    return HUMAN_REVIEW_NODE in next_nodes


async def resume_with_human_decision(
    graph: CompiledStateGraph,
    claim_id: str,
    *,
    decision: ClaimStatus,
    reviewer_note: str | None = None,
    analyst_id: str | None = None,
) -> dict:
    """Update checkpoint state with the adjuster decision and resume the graph.

    Raises:
        ValueError: If the graph is not paused before ``human_review``.
    """
    if decision not in {ClaimStatus.APPROVED, ClaimStatus.REJECTED}:
        raise ValueError(f"Unsupported human decision: {decision}")

    config = thread_config(claim_id)
    if not await is_awaiting_human_review(graph, claim_id):
        raise ValueError(
            f"Claim {claim_id} is not paused at {HUMAN_REVIEW_NODE}; cannot resume."
        )

    await graph.aupdate_state(
        config,
        {
            "human_decision": decision.value,
            "reviewer_note": reviewer_note,
            "analyst_id": analyst_id,
            "awaiting_human_decision": False,
            "graph_interrupted": False,
            "status": decision,
        },
    )
    result = await graph.ainvoke(None, config=config)
    logger.info(
        "LangGraph resumed after human decision",
        extra={
            "claim_id": claim_id,
            "decision": decision.value,
            "final_status": result.get("status"),
            "analyst_id": analyst_id,
        },
    )
    return dict(result)


def build_claim_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Construct and compile the claim processing StateGraph.

    Pipeline:
      START → triage → investigation → risk_assessment
            → [human_review | approval | rejected] → END

    ``human_review`` uses ``interrupt_before`` so the graph *pauses* and waits
    for ``resume_with_human_decision`` (review API) before completing.
    """
    graph = StateGraph(ClaimAgentState)

    graph.add_node("triage", _wrap_safe_node("triage", triage_node))
    graph.add_node("investigation", _wrap_safe_node("investigation", investigation_node))
    graph.add_node("risk_assessment", _wrap_safe_node("risk_assessment", risk_assessment_node))
    graph.add_node(HUMAN_REVIEW_NODE, _wrap_safe_node(HUMAN_REVIEW_NODE, human_review_node))
    graph.add_node("approval", _wrap_safe_node("approval", approval_node))
    graph.add_node("rejected", _wrap_safe_node("rejected", rejected_node))

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "investigation")
    graph.add_conditional_edges(
        "investigation",
        route_after_investigation,
        {
            "risk_assessment": "risk_assessment",
            "human_review": HUMAN_REVIEW_NODE,
        },
    )
    graph.add_conditional_edges(
        "risk_assessment",
        route_after_risk_assessment,
        {
            "human_review": HUMAN_REVIEW_NODE,
            "approval": "approval",
            "rejected": "rejected",
        },
    )
    graph.add_edge(HUMAN_REVIEW_NODE, END)
    graph.add_edge("approval", END)
    graph.add_edge("rejected", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=[HUMAN_REVIEW_NODE],
    )
