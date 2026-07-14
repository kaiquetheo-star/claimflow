"""Tests for LLM fallback and weather tool utilities."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claimflow.models.agent_schemas import TriageResult
from claimflow.services.llm_service import (
    MOCK_MODEL_NAME,
    MockLLM,
    ainvoke_llm_with_fallback,
    is_model_access_error,
)

_ENV_PATCH = {
    "DASHSCOPE_API_KEY": "test-key",
    "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
    "OSS_BUCKET_NAME": "test-bucket",
    "OSS_ENDPOINT": "https://oss-test.aliyuncs.com",
    "USE_MOCK_LLM": "false",
}


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        from claimflow.core.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


def test_is_model_access_error() -> None:
    assert is_model_access_error(Exception("403 AccessDenied.Unpurchased"))
    assert not is_model_access_error(Exception("timeout connecting"))


@pytest.mark.asyncio
async def test_ainvoke_llm_with_fallback_uses_second_model() -> None:
    mock_runnable = MagicMock()
    mock_runnable.ainvoke = AsyncMock(return_value="ok")

    mock_llm_fail = MagicMock()
    mock_llm_fail.with_config = MagicMock()
    mock_runnable_fail = MagicMock()
    mock_runnable_fail.ainvoke = AsyncMock(
        side_effect=Exception("403 AccessDenied.Unpurchased")
    )

    call_count = 0

    def configure(llm: MagicMock) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_runnable_fail if call_count == 1 else mock_runnable

    with patch(
        "claimflow.services.llm_service.create_chat_llm",
        side_effect=[MagicMock(), MagicMock()],
    ):
        result, model = await ainvoke_llm_with_fallback(
            [{"role": "user", "content": "hi"}],
            temperature=0.1,
            configure=configure,
        )

    assert result == "ok"
    assert model is not None


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
async def test_ainvoke_llm_with_fallback_uses_mock_when_use_mock_llm_enabled() -> None:
    from pydantic import SecretStr

    from claimflow.core.config import Settings, get_settings

    mock_settings = Settings(
        database_url=None,
        dashscope_api_key=SecretStr("test-key"),
        alibaba_cloud_access_key_id=SecretStr("test-id"),
        alibaba_cloud_access_key_secret=SecretStr("test-secret"),
        oss_bucket_name="test-bucket",
        oss_endpoint="https://oss-test.aliyuncs.com",
        use_mock_llm=True,
    )

    with patch("claimflow.services.llm_service.get_settings", return_value=mock_settings):
        get_settings.cache_clear()
        result, model = await ainvoke_llm_with_fallback(
            [{"role": "user", "content": "incêndio na cozinha"}],
            temperature=0.1,
            settings=mock_settings,
            configure=lambda llm: llm.with_structured_output(TriageResult),
            claim_id="CLM-MOCK-001",
        )

    assert model == MOCK_MODEL_NAME
    assert result.tipo_dano.value == "FOGO"

    with patch(
        "claimflow.services.llm_service.create_chat_llm",
        side_effect=AssertionError("DashScope should not be called when USE_MOCK_LLM=true"),
    ):
        await ainvoke_llm_with_fallback(
            [{"role": "user", "content": "incêndio na cozinha"}],
            temperature=0.1,
            settings=mock_settings,
            configure=lambda llm: llm.with_structured_output(TriageResult),
        )


@pytest.mark.asyncio
async def test_ainvoke_llm_with_fallback_mock_after_runnable_failures() -> None:
    mock_runnable = MagicMock()
    mock_runnable.ainvoke = AsyncMock(
        side_effect=Exception("403 AccessDenied.Unpurchased")
    )

    def configure(llm: object) -> object:
        if isinstance(llm, MockLLM):
            return llm.with_structured_output(TriageResult)
        return mock_runnable

    with (
        patch(
            "claimflow.services.llm_service.create_chat_llm",
            return_value=MagicMock(),
        ),
        patch(
            "claimflow.services.llm_service.get_llm_model_chain",
            return_value=["qwen-max", "qwen-plus"],
        ),
    ):
        result, model = await ainvoke_llm_with_fallback(
            [{"role": "user", "content": "incêndio na cozinha"}],
            temperature=0.1,
            configure=configure,
        )

    assert model == MOCK_MODEL_NAME
    assert result.tipo_dano.value == "FOGO"
