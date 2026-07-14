"""Observability: request IDs, PII redaction, Prometheus metrics."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claimflow.agents.states import ClaimStatus
from claimflow.core.config import Settings, get_settings
from claimflow.core.logging import ObservabilityFilter, StructuredFormatter, redact_pii
from claimflow.core.metrics import MetricsRegistry, metrics

_TEST_API_KEY = "cf_test_observability_key_1122334455667788"
_AUTH = {"X-API-Key": _TEST_API_KEY}
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _settings(upload_dir: str) -> Settings:
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
        use_mock_llm=True,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = _settings(str(tmp_path / "uploads"))
    get_settings.cache_clear()
    metrics.reset()

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "claim_id": "CLM-OBS-001",
            "status": ClaimStatus.APPROVED,
            "extracted_data": {},
            "fraud_risk_score": 0.1,
            "severity_score": 0.2,
            "risk_score": 0.2,
            "risk_assessment": {},
            "requires_human_review": False,
            "awaiting_human_decision": False,
            "graph_interrupted": False,
            "error": "",
        }
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
        ),
    ):
        from claimflow.tools.factory import reset_storage_client_cache

        reset_storage_client_cache()
        from claimflow.api.main import create_app

        app = create_app(settings=settings)
        with TestClient(app) as test_client:
            app.state.claim_graph = mock_graph
            yield test_client

        get_settings.cache_clear()
        reset_storage_client_cache()
        metrics.reset()


def test_redact_pii_masks_names_emails_and_cpf() -> None:
    payload = {
        "cliente_nome": "Maria Silva",
        "email": "maria@example.com",
        "tipo_dano": "AGUA",
        "note": "Contact maria@example.com or CPF 123.456.789-09",
    }
    redacted = redact_pii(payload)
    assert redacted["cliente_nome"] == "[REDACTED]"
    assert redacted["email"] == "[REDACTED]"
    assert redacted["tipo_dano"] == "AGUA"
    assert "[REDACTED]" in redacted["note"]
    assert "maria@example.com" not in redacted["note"]
    assert "123.456.789-09" not in redacted["note"]


def test_observability_filter_injects_ids_and_redacts(monkeypatch: pytest.MonkeyPatch) -> None:
    from claimflow.core import context as ctx

    ctx.set_request_id("req-123")
    ctx.set_correlation_id("CLM-CORR")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.cliente_nome = "João"
    ObservabilityFilter().filter(record)

    assert record.request_id == "req-123"
    assert record.correlation_id == "CLM-CORR"
    assert record.cliente_nome == "[REDACTED]"

    formatted = StructuredFormatter().format(record)
    assert "request_id=req-123" in formatted
    assert "correlation_id=CLM-CORR" in formatted
    assert "João" not in formatted

    ctx.set_request_id(None)
    ctx.set_correlation_id(None)


def test_request_id_middleware_sets_response_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "fixed-req-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "fixed-req-id"
    assert "X-Correlation-ID" in response.headers
    assert "X-Response-Time-Ms" in response.headers


def test_request_id_generated_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    assert len(response.headers["X-Request-ID"]) >= 8


def test_metrics_endpoint_prometheus_format(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "claims_submitted" in body
    assert "claims_approved" in body
    assert "claims_rejected" in body
    assert "avg_processing_time" in body


def test_metrics_updated_on_claim_submit(client: TestClient) -> None:
    before = metrics.snapshot()
    response = client.post(
        "/api/v1/claims/submit",
        data={
            "claim_id": "CLM-OBS-001",
            "raw_input_text": "Vazamento no apartamento após tempestade em São Paulo.",
        },
        files={"image": ("damage.png", BytesIO(_PNG), "image/png")},
        headers=_AUTH,
    )
    assert response.status_code == 202
    assert response.headers.get("X-Request-ID")

    after = metrics.snapshot()
    assert after["claims_submitted"] == before["claims_submitted"] + 1
    assert after["claims_approved"] == before["claims_approved"] + 1
    assert after["avg_processing_time"] >= 0.0
    assert after["processing_samples"] == before["processing_samples"] + 1


def test_metrics_registry_unit() -> None:
    registry = MetricsRegistry()
    registry.record_submission()
    registry.record_processing_time(1.5)
    registry.record_processing_time(0.5)
    registry.record_outcome("APPROVED")
    registry.record_outcome("REJECTED")

    snap = registry.snapshot()
    assert snap["claims_submitted"] == 1
    assert snap["claims_approved"] == 1
    assert snap["claims_rejected"] == 1
    assert snap["avg_processing_time"] == pytest.approx(1.0)

    text = registry.render_prometheus()
    assert "claims_submitted 1" in text
    assert "avg_processing_time 1.000000" in text
