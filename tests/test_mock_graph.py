"""Integration tests for offline MockLLM graph execution."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from claimflow.agents.graph import build_claim_graph, is_awaiting_human_review, thread_config
from claimflow.agents.states import ClaimStatus
from claimflow.models.agent_schemas import RiskAssessmentResult, ToolDecision, TriageResult
from claimflow.services.llm_service import MOCK_MODEL_NAME, MockLLM, ainvoke_llm_with_fallback

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


@pytest.mark.asyncio
async def test_mock_llm_structured_outputs_cover_all_schemas() -> None:
    fraud_text = "Meu apartamento pegou fogo ontem à noite"
    mock = MockLLM()
    triage = await mock.with_structured_output(TriageResult).ainvoke(
        [{"role": "user", "content": fraud_text}]
    )
    tool = await mock.with_structured_output(ToolDecision).ainvoke(
        [{"role": "user", "content": fraud_text}]
    )
    risk = await mock.with_structured_output(RiskAssessmentResult).ainvoke(
        [{"role": "user", "content": fraud_text}]
    )

    assert triage.tipo_dano.value == "FOGO"
    assert triage.cliente_nome == "Carlos Silva"
    assert tool.requires_tool_call is False
    assert risk.fraud_risk_score >= 0.85


@pytest.mark.asyncio
async def test_mock_llm_storm_scenario_auto_approve_fields() -> None:
    storm_text = "Telhado danificado por vendaval forte ontem à noite"
    mock = MockLLM()
    triage = await mock.with_structured_output(TriageResult).ainvoke(
        [{"role": "user", "content": storm_text}]
    )
    risk = await mock.with_structured_output(RiskAssessmentResult).ainvoke(
        [{"role": "user", "content": storm_text}]
    )

    assert triage.tipo_dano.value == "VENTO"
    assert triage.cliente_nome == "Maria Oliveira"
    assert risk.fraud_risk_score <= 0.2
    assert risk.requires_human_review is False


@pytest.mark.asyncio
async def test_mock_llm_ambiguous_scenario_defaults() -> None:
    mock = MockLLM()
    triage = await mock.with_structured_output(TriageResult).ainvoke([])
    risk = await mock.with_structured_output(RiskAssessmentResult).ainvoke([])

    assert triage.tipo_dano.value == "OUTRO"
    assert risk.fraud_risk_score == 0.65
    assert risk.requires_human_review is True


@pytest.mark.asyncio
async def test_ainvoke_llm_with_fallback_uses_mock_when_all_models_fail() -> None:
    with patch(
        "claimflow.services.llm_service.create_chat_llm",
        side_effect=Exception("403 AccessDenied.Unpurchased"),
    ):
        result, model = await ainvoke_llm_with_fallback(
            [{"role": "user", "content": "incêndio na cozinha"}],
            temperature=0.1,
            configure=lambda llm: llm.with_structured_output(TriageResult),
        )

    assert model == MOCK_MODEL_NAME
    assert result.tipo_dano.value == "FOGO"


@pytest.mark.asyncio
async def test_full_graph_with_mock_llm_routes_human_review(tmp_path) -> None:
    image_file = tmp_path / "damage.jpg"
    image_file.write_bytes(b"\xff\xd8\xff mock jpeg")

    initial_state = {
        "claim_id": "CLM-MOCK-001",
        "raw_input": (
            "Incêndio na cozinha em São Paulo em 15/03/2026. "
            "Cliente: Carlos Silva. A cozinha pegou fogo ontem à noite."
        ),
        "image_path": str(image_file),
        "extracted_data": {},
        "image_analysis": None,
        "consistency_score": None,
        "fraud_risk_score": 0.0,
        "severity_score": 0.0,
        "risk_score": 0.0,
        "requires_human_review": False,
        "risk_assessment": {},
        "tool_calls_made": [],
        "weather_verification": None,
        "system_error": False,
        "status": ClaimStatus.PENDING,
        "error": "",
        "error_message": "",
    }

    async def _force_mock(messages, **kwargs):
        configure = kwargs.get("configure")
        return await ainvoke_llm_with_fallback(
            messages,
            preferred_model=MOCK_MODEL_NAME,
            temperature=kwargs.get("temperature", 0.1),
            configure=configure,
        )

    with (
        patch(
            "claimflow.agents.graph.ainvoke_llm_with_fallback",
            new_callable=AsyncMock,
            side_effect=_force_mock,
        ),
        patch(
            "claimflow.services.vision_service.AioMultiModalConversation.call",
            new_callable=AsyncMock,
            side_effect=Exception("403 AccessDenied.Unpurchased"),
        ),
    ):
        graph = build_claim_graph(checkpointer=InMemorySaver())
        result = await graph.ainvoke(
            initial_state,
            config=thread_config(initial_state["claim_id"]),
        )

    assert result["status"] == ClaimStatus.HUMAN_REVIEW
    assert result["fraud_risk_score"] >= 0.85
    assert result.get("system_error") is not True
    assert result["extracted_data"]["tipo_dano"] == "FOGO"
    assert result["image_analysis"]["detected_damage_type"] == "AGUA"
    assert await is_awaiting_human_review(graph, initial_state["claim_id"]) is True
