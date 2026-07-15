"""Unit tests for Qwen-VL VisionService."""

import json
import os
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claimflow.services.vision_service import VisionService, VisionServiceError

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


def _mock_vl_response(text: str) -> MagicMock:
    response = MagicMock()
    response.status_code = HTTPStatus.OK
    choice = MagicMock()
    choice.message.content = text
    response.output.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_analyze_claim_image_success(tmp_path) -> None:
    image_file = tmp_path / "damage.jpg"
    image_file.write_bytes(b"\xff\xd8\xff fake jpeg")

    analysis = {
        "detected_damage_type": "AGUA",
        "visual_severity": "media",
        "location_match": True,
        "description": "Manchas de umidade visíveis na parede.",
        "inconsistencies": [],
    }
    mock_response = _mock_vl_response(json.dumps(analysis))

    with patch(
        "claimflow.services.vision_service.AioMultiModalConversation.call",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        service = VisionService()
        result = await service.analyze_claim_image(str(image_file), "Vazamento de água.")

    assert result["detected_damage_type"] == "AGUA"
    assert result["visual_severity"] == "media"
    assert result["location_match"] is True


@pytest.mark.asyncio
async def test_analyze_claim_image_api_error_returns_mock(tmp_path) -> None:
    image_file = tmp_path / "damage.png"
    image_file.write_bytes(b"\x89PNG fake")

    mock_response = MagicMock()
    mock_response.status_code = HTTPStatus.BAD_REQUEST
    mock_response.code = "InvalidParameter"
    mock_response.message = "bad request"

    with patch(
        "claimflow.services.vision_service.AioMultiModalConversation.call",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        service = VisionService()
        result = await service.analyze_claim_image(
            str(image_file),
            "Apartment fire last night.",
            language="en",
        )

    assert result["detected_damage_type"] == "AGUA"
    assert result["source"] == "mock"
    assert "Mock image" in result["description"]
    assert any("fire" in item.lower() for item in result["inconsistencies"])
    assert not any("incêndio" in item.lower() for item in result["inconsistencies"])


def test_build_mock_analysis_localizes_free_text() -> None:
    en = VisionService.build_mock_analysis("Kitchen caught fire yesterday", "en")
    pt = VisionService.build_mock_analysis("Incêndio na cozinha ontem", "pt")
    assert "Mock image" in en["description"]
    assert "Imagem mock" in pt["description"]
    assert any("fire" in item.lower() for item in en["inconsistencies"])
    assert any("incêndio" in item.lower() for item in pt["inconsistencies"])


@pytest.mark.asyncio
async def test_analyze_claim_image_timeout_returns_mock(tmp_path) -> None:
    image_file = tmp_path / "damage.webp"
    image_file.write_bytes(b"RIFF fake webp")

    async def slow_call(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(10)

    with patch(
        "claimflow.services.vision_service.AioMultiModalConversation.call",
        side_effect=slow_call,
    ):
        service = VisionService()
        with patch.object(service._settings, "vision_timeout_seconds", 0.01):
            result = await service.analyze_claim_image(str(image_file), "Relato de incêndio.")

    assert result["source"] == "mock"
    assert result["detected_damage_type"] == "AGUA"


@pytest.mark.asyncio
async def test_analyze_claim_image_invalid_format(tmp_path) -> None:
    bad_file = tmp_path / "document.pdf"
    bad_file.write_bytes(b"%PDF-1.4")

    service = VisionService()
    with pytest.raises(VisionServiceError, match="Unsupported image format"):
        await service.analyze_claim_image(str(bad_file), "Relato.")


def test_compute_consistency_score_exact_match() -> None:
    score = VisionService.compute_consistency_score("AGUA", "vazamento de água")
    assert score == 1.0


def test_compute_consistency_score_severe_mismatch() -> None:
    score = VisionService.compute_consistency_score("FOGO", "AGUA")
    assert score == 0.0


def test_compute_consistency_score_partial_match() -> None:
    score = VisionService.compute_consistency_score("OUTRO", "FOGO")
    assert score == 0.5
