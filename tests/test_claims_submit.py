"""End-to-end tests for claim submission and the review handoff flow."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.agents.states import ClaimStatus
from claimflow.api.file_validation import MAX_UPLOAD_BYTES
from claimflow.core.config import Settings, get_settings

_TEST_API_KEY = "cf_test_claims_submit_key_a1b2c3d4e5f67890"
_AUTH_HEADERS = {"X-API-Key": _TEST_API_KEY}

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_PDF = b"%PDF-1.4 spoofed"

LEGIT_CLAIM_TEXT = (
    "Assunto: Sinistro por tempestade\n\n"
    "Olá, sou Ana Paula. A tempestade de ontem em São Paulo causou vazamento "
    "no telhado do apartamento. Preciso de cobertura do seguro."
)

FRAUD_CLAIM_TEXT = (
    "Assunto: Sinistro residencial — incêndio\n\n"
    "Sou Carlos Mendes. Meu apartamento pegou fogo. Preciso de indenização urgente."
)


def _build_settings(upload_dir: str, *, use_mock_llm: bool = True) -> Settings:
    return Settings(
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        api_key=SecretStr(_TEST_API_KEY),
        storage_backend="local",
        database_url=None,
        local_upload_dir=upload_dir,
        local_upload_base_url="http://localhost:8000",
        use_mock_llm=use_mock_llm,
    )


def _graph_result(
    claim_id: str,
    *,
    status: ClaimStatus = ClaimStatus.APPROVED,
    fraud_risk_score: float = 0.15,
    risk_score: float = 0.2,
    requires_human_review: bool = False,
    extracted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "status": status,
        "extracted_data": extracted
        or {
            "cliente_nome": "Ana Paula",
            "tipo_dano": "AGUA",
            "localizacao": "São Paulo",
        },
        "image_analysis": None,
        "consistency_score": None,
        "fraud_risk_score": fraud_risk_score,
        "severity_score": 0.4,
        "risk_score": risk_score,
        "risk_assessment": {"reasoning": "Deterministic mock assessment"},
        "requires_human_review": requires_human_review,
        "awaiting_human_decision": False,
        "graph_interrupted": False,
        "error": "",
        "error_message": "",
        "tool_calls_made": [],
        "weather_verification": None,
        "system_error": False,
        "human_decision": None,
        "reviewer_note": None,
        "analyst_id": None,
    }


@dataclass
class SubmitHarness:
    """Test client plus injectable LangGraph mocks."""

    client: TestClient
    settings: Settings
    mock_graph: MagicMock
    mock_awaiting_claims: AsyncMock
    mock_awaiting_review: AsyncMock
    mock_resume: AsyncMock


@pytest.fixture
def png_bytes() -> bytes:
    return _PNG


@pytest.fixture
def sample_claim() -> dict[str, str]:
    return {
        "claim_id": "CLM-E2E-001",
        "raw_input_text": LEGIT_CLAIM_TEXT,
    }


@pytest.fixture
def harness(tmp_path: Path) -> SubmitHarness:
    """FastAPI app with LangGraph mocked for fast, deterministic e2e tests."""
    settings = _build_settings(str(tmp_path / "uploads"), use_mock_llm=True)
    get_settings.cache_clear()

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        side_effect=lambda state, config=None: _graph_result(state["claim_id"])
    )

    with (
        patch("claimflow.core.config.get_settings", return_value=settings),
        patch("claimflow.api.dependencies.get_settings", return_value=settings),
        patch("claimflow.tools.factory.get_settings", return_value=settings),
        patch(
            "claimflow.services.alibaba_cloud_integration.verify_alibaba_cloud_connection",
            new_callable=AsyncMock,
            return_value={
                "status": "healthy",
                "alibaba_cloud_services": {
                    "qwen_cloud": {"status": "connected"},
                    "oss": {"status": "configured", "backend": "local"},
                    "ram": {"status": "configured"},
                },
            },
        ),
        patch(
            "claimflow.api.routes.claims.is_awaiting_human_review",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_awaiting_claims,
        patch(
            "claimflow.api.routes.review.is_awaiting_human_review",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_awaiting_review,
        patch(
            "claimflow.api.routes.review.resume_with_human_decision",
            new_callable=AsyncMock,
        ) as mock_resume,
    ):
        from claimflow.tools.factory import reset_storage_client_cache

        reset_storage_client_cache()
        from claimflow.api.main import create_app

        app = create_app(settings=settings)

        with TestClient(app) as client:
            # Lifespan builds a real graph; replace it after startup for fast tests.
            app.state.claim_graph = mock_graph
            yield SubmitHarness(
                client=client,
                settings=settings,
                mock_graph=mock_graph,
                mock_awaiting_claims=mock_awaiting_claims,
                mock_awaiting_review=mock_awaiting_review,
                mock_resume=mock_resume,
            )

        get_settings.cache_clear()
        reset_storage_client_cache()


def test_submit_success_with_valid_data(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
    png_bytes: bytes,
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
        files={"image": ("damage.png", BytesIO(png_bytes), "image/png")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["claim_id"] == sample_claim["claim_id"]
    assert body["status"] == ClaimStatus.APPROVED.value
    assert body["extracted_data"]["cliente_nome"] == "Ana Paula"
    assert body["fraud_risk_score"] == pytest.approx(0.15)
    assert body["error"] is None
    harness.mock_graph.ainvoke.assert_awaited_once()


def test_submit_accepts_language_and_passes_to_graph_state(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    """POST /claims/submit accepts language and injects it into LangGraph state."""
    data = {**sample_claim, "language": "pt"}
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=data,
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 202
    harness.mock_graph.ainvoke.assert_awaited_once()
    call_args = harness.mock_graph.ainvoke.await_args
    initial_state = call_args.args[0]
    assert initial_state["language"] == "pt"


def test_submit_defaults_language_to_english(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 202
    initial_state = harness.mock_graph.ainvoke.await_args.args[0]
    assert initial_state["language"] == "en"


def test_submit_rejects_unsupported_language(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data={**sample_claim, "language": "fr"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 422


def test_submit_with_mock_llm_deterministic_response(harness: SubmitHarness) -> None:
    """MockLLM mode is enabled; graph mock returns fixed fraud-scenario scores."""
    assert harness.settings.use_mock_llm is True

    claim_id = "CLM-E2E-MOCK"
    fraud_result = _graph_result(
        claim_id,
        status=ClaimStatus.REJECTED,
        fraud_risk_score=0.95,
        risk_score=0.92,
        requires_human_review=False,
        extracted={
            "cliente_nome": "Carlos Mendes",
            "tipo_dano": "FOGO",
            "localizacao": "São Paulo",
        },
    )
    harness.mock_graph.ainvoke = AsyncMock(return_value=fraud_result)

    response = harness.client.post(
        "/api/v1/claims/submit",
        data={"claim_id": claim_id, "raw_input_text": FRAUD_CLAIM_TEXT},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == ClaimStatus.REJECTED.value
    assert body["fraud_risk_score"] == pytest.approx(0.95)
    assert body["risk_score"] == pytest.approx(0.92)
    assert body["extracted_data"]["tipo_dano"] == "FOGO"

    # Same input → same deterministic payload on a second call
    harness.mock_graph.ainvoke = AsyncMock(return_value=fraud_result)
    second = harness.client.post(
        "/api/v1/claims/submit",
        data={"claim_id": "CLM-E2E-MOCK-2", "raw_input_text": FRAUD_CLAIM_TEXT},
        headers=_AUTH_HEADERS,
    )
    assert second.status_code == 202
    assert second.json()["fraud_risk_score"] == body["fraud_risk_score"]


def test_submit_without_image_still_works(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["claim_id"] == sample_claim["claim_id"]
    assert body["status"] == ClaimStatus.APPROVED.value
    assert body["image_analysis"] is None

    call_args = harness.mock_graph.ainvoke.await_args
    initial_state = call_args.args[0]
    assert initial_state["image_path"] is None
    assert initial_state["raw_input"] == sample_claim["raw_input_text"]


def test_submit_invalid_file_type_returns_422(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
        files={"image": ("malware.exe", BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422
    assert "extension" in response.json()["detail"].lower()
    harness.mock_graph.ainvoke.assert_not_called()


def test_submit_oversized_file_returns_413(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_UPLOAD_BYTES
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
        files={"image": ("huge.png", BytesIO(oversized), "image/png")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]
    harness.mock_graph.ainvoke.assert_not_called()


def test_submit_without_api_key_returns_401(
    harness: SubmitHarness,
    sample_claim: dict[str, str],
) -> None:
    response = harness.client.post(
        "/api/v1/claims/submit",
        data=sample_claim,
    )

    assert response.status_code == 401
    assert "API key" in response.json()["detail"]
    harness.mock_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_full_flow_submit_to_review_to_decision(harness: SubmitHarness) -> None:
    """submit → processing (paused) → review queue → approve decision."""
    claim_id = "CLM-E2E-HITL"

    pending = _graph_result(
        claim_id,
        status=ClaimStatus.PENDING,
        fraud_risk_score=0.8,
        risk_score=0.75,
        requires_human_review=True,
        extracted={
            "cliente_nome": "Carlos Mendes",
            "tipo_dano": "FOGO",
            "localizacao": "São Paulo",
        },
    )
    harness.mock_graph.ainvoke = AsyncMock(return_value=pending)
    harness.mock_awaiting_claims.return_value = True

    # 1) Submit — graph pauses before human_review
    submit = harness.client.post(
        "/api/v1/claims/submit",
        data={"claim_id": claim_id, "raw_input_text": FRAUD_CLAIM_TEXT},
        headers=_AUTH_HEADERS,
    )
    assert submit.status_code == 202
    submit_body = submit.json()
    assert submit_body["status"] == ClaimStatus.HUMAN_REVIEW.value
    assert submit_body["awaiting_human_decision"] is True
    assert submit_body["graph_interrupted"] is True
    assert submit_body["requires_human_review"] is True

    # 2) Claim appears on the review queue
    queue = harness.client.get("/api/v1/review/queue")
    assert queue.status_code == 200
    queue_body = queue.json()
    assert any(item["claim_id"] == claim_id for item in queue_body["items"])

    # 3) Adjuster records a decision (resume mocked for speed)
    harness.mock_awaiting_review.return_value = True
    harness.mock_resume.return_value = {
        **pending,
        "status": ClaimStatus.APPROVED,
        "human_decision": "APPROVED",
        "awaiting_human_decision": False,
        "graph_interrupted": False,
    }

    decision = harness.client.post(
        f"/api/v1/review/{claim_id}/decision",
        json={
            "decision": "approved",
            "analyst_notes": "Documentação validada após análise manual.",
            "analyst_id": "demo-analyst",
        },
        headers=_AUTH_HEADERS,
    )
    assert decision.status_code == 200
    decision_body = decision.json()
    assert decision_body["claim_id"] == claim_id
    assert decision_body["status"] == ClaimStatus.APPROVED.value
    assert decision_body["reviewer_note"] == "Documentação validada após análise manual."
    assert decision_body["analyst_id"] == "demo-analyst"
    harness.mock_resume.assert_awaited_once()

    # 4) Claim is no longer waiting in the human-review queue
    queue_after = harness.client.get("/api/v1/review/queue")
    assert queue_after.status_code == 200
    assert all(item["claim_id"] != claim_id for item in queue_after.json()["items"])
