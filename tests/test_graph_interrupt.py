"""Tests for LangGraph interrupt_before human_review and resume."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from claimflow.agents.graph import (
    build_claim_graph,
    is_awaiting_human_review,
    resume_with_human_decision,
    thread_config,
)
from claimflow.agents.states import ClaimStatus
from claimflow.models.agent_schemas import (
    RiskAssessmentResult,
    TipoDano,
    ToolDecision,
    TriageResult,
)

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


def _initial_state(claim_id: str, raw_input: str) -> dict:
    return {
        "claim_id": claim_id,
        "raw_input": raw_input,
        "image_path": None,
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
        "awaiting_human_decision": False,
        "graph_interrupted": False,
        "human_decision": None,
        "reviewer_note": None,
        "analyst_id": None,
    }


@pytest.mark.asyncio
async def test_graph_pauses_before_human_review() -> None:
    triage = TriageResult(
        cliente_nome="Carlos Silva",
        tipo_dano=TipoDano.FOGO,
        localizacao="Rio de Janeiro, RJ",
        descricao_resumida="Cozinha pegou fogo ontem",
        data_incidente=None,
    )
    tool = ToolDecision(
        requires_tool_call=False,
        tool_name="none",
        tool_arguments={},
        reasoning="Sem clima.",
    )
    risk = RiskAssessmentResult(
        fraud_risk_score=0.88,
        severity_score=0.7,
        justificativa_risco="Inconsistência alta.",
        requires_human_review=True,
    )

    call_n = {"i": 0}

    async def _llm_seq(messages, **kwargs):
        call_n["i"] += 1
        if call_n["i"] == 1:
            return triage, "mock"
        if call_n["i"] == 2:
            return tool, "mock"
        return risk, "mock"

    graph = build_claim_graph(checkpointer=InMemorySaver())
    claim_id = "CLM-INT-001"
    config = thread_config(claim_id)

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        side_effect=_llm_seq,
    ):
        result = await graph.ainvoke(
            _initial_state(claim_id, "Incêndio na cozinha, pegou fogo"),
            config=config,
        )

    assert result["status"] == ClaimStatus.HUMAN_REVIEW
    assert await is_awaiting_human_review(graph, claim_id) is True
    snapshot = await graph.aget_state(config)
    assert "human_review" in (snapshot.next or ())


@pytest.mark.asyncio
async def test_resume_with_human_decision_approves() -> None:
    triage = TriageResult(
        cliente_nome="Carlos Silva",
        tipo_dano=TipoDano.FOGO,
        localizacao="Rio",
        descricao_resumida="Fogo",
        data_incidente=None,
    )
    tool = ToolDecision(
        requires_tool_call=False,
        tool_name="none",
        tool_arguments={},
        reasoning="n/a",
    )
    risk = RiskAssessmentResult(
        fraud_risk_score=0.88,
        severity_score=0.7,
        justificativa_risco="Alto risco.",
        requires_human_review=True,
    )
    call_n = {"i": 0}

    async def _llm_seq(messages, **kwargs):
        call_n["i"] += 1
        if call_n["i"] == 1:
            return triage, "mock"
        if call_n["i"] == 2:
            return tool, "mock"
        return risk, "mock"

    graph = build_claim_graph(checkpointer=InMemorySaver())
    claim_id = "CLM-INT-002"
    config = thread_config(claim_id)

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        side_effect=_llm_seq,
    ):
        await graph.ainvoke(
            _initial_state(claim_id, "Apartamento pegou fogo ontem"),
            config=config,
        )

    final = await resume_with_human_decision(
        graph,
        claim_id,
        decision=ClaimStatus.APPROVED,
        reviewer_note="Override after investigation.",
        analyst_id="demo-analyst",
    )

    assert final["status"] == ClaimStatus.APPROVED
    assert final.get("awaiting_human_decision") is False
    assert await is_awaiting_human_review(graph, claim_id) is False
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ()


@pytest.mark.asyncio
async def test_auto_approve_path_does_not_interrupt() -> None:
    triage = TriageResult(
        cliente_nome="Maria",
        tipo_dano=TipoDano.OUTRO,
        localizacao="São Paulo",
        descricao_resumida="Pequeno dano no piso",
        data_incidente=None,
    )
    tool = ToolDecision(
        requires_tool_call=False,
        tool_name="none",
        tool_arguments={},
        reasoning="skip",
    )
    risk = RiskAssessmentResult(
        fraud_risk_score=0.1,
        severity_score=0.2,
        justificativa_risco="Baixo risco.",
        requires_human_review=False,
    )
    call_n = {"i": 0}

    async def _llm_seq(messages, **kwargs):
        call_n["i"] += 1
        if call_n["i"] == 1:
            return triage, "mock"
        if call_n["i"] == 2:
            return tool, "mock"
        return risk, "mock"

    graph = build_claim_graph(checkpointer=InMemorySaver())
    claim_id = "CLM-INT-003"

    with patch(
        "claimflow.agents.graph.ainvoke_llm_with_fallback",
        new_callable=AsyncMock,
        side_effect=_llm_seq,
    ):
        result = await graph.ainvoke(
            _initial_state(claim_id, "Pequeno dano no piso do apartamento"),
            config=thread_config(claim_id),
        )

    assert result["status"] == ClaimStatus.APPROVED
    assert await is_awaiting_human_review(graph, claim_id) is False
