"""Tests for Open-Meteo weather history integration."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from claimflow.tools.weather_tool import (
    ARCHIVE_URL,
    GEOCODING_URL,
    get_weather_history,
    parse_incident_date,
)


def test_parse_incident_date_iso_and_brazilian() -> None:
    assert parse_incident_date("2026-03-15") == "2026-03-15"
    assert parse_incident_date("15/03/2026") == "2026-03-15"
    assert parse_incident_date("ontem", today=date(2026, 7, 7)) == "2026-07-06"


def test_parse_incident_date_invalid() -> None:
    assert parse_incident_date("data desconhecida") is None


def _mock_http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_get_weather_history_success() -> None:
    geo_payload = {
        "results": [
            {
                "latitude": -23.55,
                "longitude": -46.63,
                "name": "São Paulo",
                "country_code": "BR",
                "admin1": "São Paulo",
            }
        ]
    }
    archive_payload = {
        "daily": {
            "time": ["2024-03-15"],
            "precipitation_sum": [45.0],
            "windspeed_10m_max": [50.0],
            "weathercode": [61],
        }
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[
            _mock_http_response(geo_payload),
            _mock_http_response(archive_payload),
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("claimflow.tools.weather_tool.httpx.AsyncClient", return_value=mock_client):
        result = await get_weather_history("São Paulo, SP", "2024-03-15")

    assert result["source"] == "open-meteo"
    assert result["had_heavy_rain"] is True
    assert result["had_strong_winds"] is True
    assert "45mm" in result["summary"]
    assert result["location_verified"].startswith("São Paulo")

    assert mock_client.get.await_count == 2
    first_call = mock_client.get.await_args_list[0]
    assert first_call.args[0] == GEOCODING_URL
    second_call = mock_client.get.await_args_list[1]
    assert second_call.args[0] == ARCHIVE_URL


@pytest.mark.asyncio
async def test_get_weather_history_geolocation_failed() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_http_response({"results": []}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("claimflow.tools.weather_tool.httpx.AsyncClient", return_value=mock_client):
        result = await get_weather_history("CidadeInexistente XYZ", "2024-03-15")

    assert result["error"] == "geolocation_failed"
    assert "No coordinates found" in result["message"]


@pytest.mark.asyncio
async def test_get_weather_history_network_error() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("claimflow.tools.weather_tool.httpx.AsyncClient", return_value=mock_client):
        result = await get_weather_history("São Paulo", "2024-03-15")

    assert result["error"] == "network_error"


@pytest.mark.asyncio
async def test_get_weather_history_invalid_date() -> None:
    result = await get_weather_history("São Paulo", "quando der")
    assert result["error"] == "invalid_date"
