"""Unit tests for LangGraph nodes with mocked LLM responses."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from claimflow.agents.graph import (
    FAIL_CLOSED_REASON,
    _compute_fail_closed_penalties,
    _mentions_weather_climate,
    _resolve_status,
    investigation_node,
    risk_assessment_node,
    route_after_investigation,
    route_after_risk_assessment,
    triage_node,
)
from claimflow.agents.states import ClaimStatus
from claimflow.models.agent_schemas import (
    RiskAssessmentResult,
    TipoDano,
    ToolDecision,
    TriageResult,
)
from claimflow.services.llm_service import MOCK_MODEL_NAME, LLMInvocationError
from claimflow.services.vision_service import VisionService

_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


def _base_state() -> dict:
    return {
        "claim_id": "CLM-TEST-001",
        "raw_input": "Sinistro de água em São Paulo.",
        "extracted_data": {},
        "fraud_risk_score": 0.0,
        "severity_score": 0.0,
        "risk_score": 0.0,
        "requires_human_review": False,
        "risk_assessment": {},
        "tool_calls_made": [],
        "system_error": False,
        "status": ClaimStatus.PENDING,
        "error": "",
        "error_message": "",
    }


@pytest.mark.asyncio
async def test_triage_node_success() -> None:
    triage_result = TriageResult(
        cliente_nome="Maria Silva",
        tipo_dano=TipoDano.AGUA,
        localizacao="São Paulo, SP",
        descricao_resumida="Vazamento de água no apartamento.",
        data_incidente=datetime(2026, 3, 15),
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(triage_result, "qwen-plus"),
    ):
        result = await triage_node(_base_state())

    assert result["extracted_data"]["cliente_nome"] == "Maria Silva"
    assert result["extracted_data"]["tipo_dano"] == "AGUA"
    assert result["status"] == ClaimStatus.PENDING


@pytest.mark.asyncio
async def test_triage_node_with_vision_cross_validation() -> None:
    triage_result = TriageResult(
        cliente_nome="Maria Silva",
        tipo_dano=TipoDano.FOGO,
        localizacao="São Paulo, SP",
        descricao_resumida="Incêndio no apartamento.",
        data_incidente=datetime(2026, 3, 15),
    )
    vision_analysis = {
        "detected_damage_type": "AGUA",
        "visual_severity": "media",
        "location_match": False,
        "description": "Manchas de umidade.",
        "inconsistencies": ["Texto relata fogo, imagem mostra água."],
    }

    state = {
        **_base_state(),
        "image_path": "/tmp/fake.jpg",
        "raw_input": "Incêndio causou danos.",
    }

    with (
        patch(
            "claimflow.agents.graph.ainvoke_llm_with_fallback",
            new_callable=AsyncMock,
            return_value=(triage_result, "qwen-plus"),
        ),
        patch.object(
            VisionService,
            "analyze_claim_image",
            new_callable=AsyncMock,
            return_value=vision_analysis,
        ),
    ):
        result = await triage_node(state)

    assert result["consistency_score"] == 0.0
    assert result["fraud_risk_score"] == 0.85
    assert result["image_analysis"]["detected_damage_type"] == "AGUA"


@pytest.mark.asyncio
async def test_triage_node_failure_escalates_to_human_review() -> None:
    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        side_effect=ValueError("LLM parse error"),
    ):
        result = await triage_node(_base_state())

    assert result["status"] == ClaimStatus.HUMAN_REVIEW
    assert result["system_error"] is True
    assert result["fraud_risk_score"] == 1.0
    assert "Triage failed" in result["error_message"]


@pytest.mark.asyncio
async def test_triage_node_all_models_fail_uses_mock_llm() -> None:
    mock_triage = TriageResult(
        cliente_nome="João Silva",
        tipo_dano=TipoDano.FOGO,
        localizacao="São Paulo, SP",
        descricao_resumida="Mock triage.",
        data_incidente=None,
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(mock_triage, MOCK_MODEL_NAME),
    ):
        result = await triage_node(_base_state())

    assert result["status"] == ClaimStatus.PENDING
    assert result["extracted_data"]["tipo_dano"] == "FOGO"
    assert result.get("system_error") is not True


@pytest.mark.asyncio
async def test_investigation_node_executes_weather_tool_on_tool_decision() -> None:
    tool_decision = ToolDecision(
        requires_tool_call=True,
        tool_name="get_weather_history",
        tool_arguments={"location": "São Paulo, SP", "date": "2026-03-15"},
        reasoning="Cliente mencionou chuva forte com local e data.",
    )
    weather_result = {
        "location_verified": "São Paulo, BR",
        "date": "2026-03-15",
        "had_heavy_rain": True,
        "had_strong_winds": False,
        "summary": "O dia teve 45mm de chuva.",
        "source": "open-meteo",
    }

    with (
        patch(
            "claimflow.agents.graph.ainvoke_llm_with_fallback",
            new_callable=AsyncMock,
            return_value=(tool_decision, "qwen-plus"),
        ),
        patch(
            "claimflow.agents.graph.get_weather_history",
            new_callable=AsyncMock,
            return_value=weather_result,
        ),
    ):
        result = await investigation_node(
            {
                **_base_state(),
                "raw_input": "Chuva forte causou alagamento em São Paulo em 15/03/2026.",
            }
        )

    assert "get_weather_history" in result["tool_calls_made"]
    assert result["weather_verification"] is not None
    assert "summary" in result["weather_verification"]
    assert result.get("system_error") is not True


@pytest.mark.asyncio
async def test_investigation_node_skips_tool_when_not_required() -> None:
    tool_decision = ToolDecision(
        requires_tool_call=False,
        tool_name="none",
        tool_arguments={},
        reasoning="Nenhuma menção a eventos climáticos no relato.",
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(tool_decision, "qwen-plus"),
    ):
        result = await investigation_node(_base_state())

    assert result["tool_calls_made"] == []
    assert result.get("weather_verification") is None


@pytest.mark.asyncio
async def test_investigation_node_routes_to_human_review_on_llm_failure() -> None:
    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        side_effect=LLMInvocationError("All failed", ["qwen-max: 403"]),
    ):
        result = await investigation_node(_base_state())

    assert result["status"] == ClaimStatus.HUMAN_REVIEW
    assert result["system_error"] is True


@pytest.mark.asyncio
async def test_risk_assessment_node_fail_closed_empty_extracted_data() -> None:
    result = await risk_assessment_node(_base_state())

    assert result["status"] == ClaimStatus.HUMAN_REVIEW
    assert result["fraud_risk_score"] == 1.0
    assert result["error"] == FAIL_CLOSED_REASON
    assert result["risk_assessment"]["fail_closed_reason"] == FAIL_CLOSED_REASON


@pytest.mark.asyncio
async def test_risk_assessment_node_penalizes_missing_image_analysis() -> None:
    state = {
        **_base_state(),
        "image_path": "/tmp/fake.jpg",
        "image_analysis": None,
        "extracted_data": {
            "cliente_nome": "Maria Silva",
            "tipo_dano": "AGUA",
            "localizacao": "São Paulo",
            "descricao_resumida": "Vazamento.",
        },
    }
    risk_result = RiskAssessmentResult(
        fraud_risk_score=0.1,
        severity_score=0.2,
        justificativa_risco="Sem indícios relevantes.",
        requires_human_review=False,
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(risk_result, "qwen-plus"),
    ):
        result = await risk_assessment_node(state)

    assert result["fraud_risk_score"] == pytest.approx(0.4)
    assert result["requires_human_review"] is True
    assert "Image provided but visual analysis unavailable" in str(
        result["risk_assessment"]["fail_closed_penalties"]
    )


@pytest.mark.asyncio
async def test_risk_assessment_node_penalizes_missing_weather_verification() -> None:
    state = {
        **_base_state(),
        "raw_input": "Tempestade com chuva forte em São Paulo ontem.",
        "extracted_data": {
            "cliente_nome": "João",
            "tipo_dano": "AGUA",
            "localizacao": "São Paulo",
            "descricao_resumida": "Alagamento por chuva.",
        },
        "weather_verification": None,
    }
    risk_result = RiskAssessmentResult(
        fraud_risk_score=0.1,
        severity_score=0.2,
        justificativa_risco="Relato coerente.",
        requires_human_review=False,
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(risk_result, "qwen-plus"),
    ):
        result = await risk_assessment_node(state)

    assert result["fraud_risk_score"] == pytest.approx(0.3)
    assert result["requires_human_review"] is True


@pytest.mark.asyncio
async def test_system_error_state_never_leaves_zero_fraud_score() -> None:
    from claimflow.agents.graph import _system_error_state

    result = _system_error_state(_base_state(), "triage", "Triage failed")

    assert result["fraud_risk_score"] == 1.0
    assert result["status"] == ClaimStatus.HUMAN_REVIEW


def test_mentions_weather_climate() -> None:
    assert _mentions_weather_climate("Chuva forte ontem em São Paulo") is True
    assert _mentions_weather_climate("Vazamento no apartamento") is False


def test_compute_fail_closed_penalties() -> None:
    bonus, penalties = _compute_fail_closed_penalties(
        {
            **_base_state(),
            "image_path": "/tmp/x.jpg",
            "raw_input": "Tempestade com vendaval",
        }
    )
    assert bonus == pytest.approx(0.5)
    assert len(penalties) == 2


@pytest.mark.asyncio
async def test_risk_assessment_node_approves_low_risk() -> None:
    state = {
        **_base_state(),
        "extracted_data": {
            "cliente_nome": "Maria Silva",
            "tipo_dano": "AGUA",
            "localizacao": "São Paulo",
            "descricao_resumida": "Pequeno vazamento.",
        },
    }
    risk_result = RiskAssessmentResult(
        fraud_risk_score=0.1,
        severity_score=0.2,
        justificativa_risco="Sinistro rotineiro sem indícios de fraude.",
        requires_human_review=False,
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(risk_result, "qwen-plus"),
    ):
        result = await risk_assessment_node(state)

    assert result["status"] == ClaimStatus.APPROVED
    assert result["fraud_risk_score"] == 0.1
    assert result["risk_score"] == 0.2


@pytest.mark.asyncio
async def test_risk_assessment_node_rejects_high_fraud() -> None:
    state = {
        **_base_state(),
        "extracted_data": {"cliente_nome": "João", "tipo_dano": "FOGO"},
    }
    risk_result = RiskAssessmentResult(
        fraud_risk_score=0.95,
        severity_score=0.8,
        justificativa_risco="Múltiplas inconsistências no relato.",
        requires_human_review=True,
    )

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        return_value=(risk_result, "qwen-plus"),
    ):
        result = await risk_assessment_node(state)

    assert result["status"] == ClaimStatus.REJECTED


def test_resolve_status_thresholds() -> None:
    assert _resolve_status(0.1, 0.2, False) == ClaimStatus.APPROVED
    assert _resolve_status(0.75, 0.5, False) == ClaimStatus.HUMAN_REVIEW
    assert _resolve_status(0.95, 0.5, False) == ClaimStatus.REJECTED
    assert _resolve_status(0.1, 0.1, True) == ClaimStatus.HUMAN_REVIEW


def test_route_after_investigation() -> None:
    assert route_after_investigation({"system_error": True}) == "human_review"
    assert route_after_investigation({"system_error": False}) == "risk_assessment"


def test_route_after_risk_assessment() -> None:
    assert route_after_risk_assessment({"status": ClaimStatus.APPROVED}) == "approval"
    assert route_after_risk_assessment({"status": ClaimStatus.HUMAN_REVIEW}) == "human_review"
    assert route_after_risk_assessment({"status": ClaimStatus.REJECTED}) == "rejected"
