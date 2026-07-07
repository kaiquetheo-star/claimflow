"""Weather history lookup via Open-Meteo (free, no API key required)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import httpx

from claimflow.core.logging import get_logger

logger = get_logger(__name__)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT_SECONDS = 15.0

HEAVY_RAIN_MM = 20.0
STRONG_WIND_KMH = 40.0

_DAILY_FIELDS = "precipitation_sum,windspeed_10m_max,weathercode"


def _error_response(
    error: str,
    message: str,
    *,
    location: str,
    date_input: str,
    parsed_date: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": error,
        "message": message,
        "location": location,
        "date": parsed_date or date_input,
    }
    return payload


def parse_incident_date(date_input: str, *, today: date | None = None) -> str | None:
    """Parse free-text or ISO dates into ``YYYY-MM-DD`` for Open-Meteo."""
    text = date_input.strip().lower()
    reference = today or date.today()

    if text in {"hoje", "today"}:
        return reference.isoformat()
    if text in {"ontem", "yesterday"}:
        return (reference - timedelta(days=1)).isoformat()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    br_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if br_match:
        day, month, year = (int(br_match.group(i)) for i in range(1, 4))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    iso_match = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
    if iso_match:
        day, month, year = (int(iso_match.group(i)) for i in range(1, 4))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    return None


def _geocoding_search_name(location: str) -> str:
    """Use the city portion before a comma/state suffix when present."""
    primary = location.split(",")[0].strip()
    return primary or location.strip()


def _format_location_verified(result: dict[str, Any]) -> str:
    name = str(result.get("name", "")).strip()
    admin1 = str(result.get("admin1", "")).strip()
    country = str(result.get("country_code", "")).strip()
    parts = [part for part in (name, admin1, country) if part]
    if not parts:
        return name or "unknown"
    if country and country not in name:
        return f"{name}, {country}" if not admin1 else f"{name}, {admin1}, {country}"
    return ", ".join(parts)


def _build_summary(precipitation_mm: float, wind_kmh: float) -> str:
    rain_part = f"{precipitation_mm:.0f}mm de chuva"
    wind_part = f"ventos de até {wind_kmh:.0f}km/h"
    if precipitation_mm <= 0 and wind_kmh <= 0:
        return "Sem precipitação registrada e sem vento significativo."
    if precipitation_mm <= 0:
        return f"Sem chuva registrada e {wind_part}."
    if wind_kmh <= 0:
        return f"O dia teve {rain_part}."
    return f"O dia teve {rain_part} e {wind_part}."


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    logger.info("Open-Meteo HTTP request", extra={"url": url, "params": params})
    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Open-Meteo response is not a JSON object")
    return payload


async def get_weather_history(location: str, date: str) -> dict[str, Any]:
    """Return historical weather for a location on a given date using Open-Meteo.

    Flow:
    1. Geocode ``location`` via Open-Meteo Geocoding API (lat/lon).
    2. Query Archive API for daily precipitation and max wind on ``date``.

    Args:
        location: City or address (e.g. ``"São Paulo, SP"``).
        date: Incident date (``YYYY-MM-DD``, ``DD/MM/YYYY``, ``ontem``, etc.).

    Returns:
        Friendly dict for LLM consumption, or a dict with ``error`` on failure.
    """
    location = location.strip()
    date_input = date.strip()

    if not location:
        return _error_response(
            "invalid_input",
            "Location must not be empty.",
            location=location,
            date_input=date_input,
        )

    parsed_date = parse_incident_date(date_input)
    if parsed_date is None:
        return _error_response(
            "invalid_date",
            f"Could not parse date: {date_input!r}",
            location=location,
            date_input=date_input,
        )

    search_name = _geocoding_search_name(location)
    geocoding_params = {"name": search_name, "count": 1}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            geocoding_payload = await _fetch_json(client, GEOCODING_URL, geocoding_params)
            results = geocoding_payload.get("results") or []
            if not results:
                return _error_response(
                    "geolocation_failed",
                    f"No coordinates found for location: {location!r}",
                    location=location,
                    date_input=date_input,
                    parsed_date=parsed_date,
                )

            geo = results[0]
            latitude = geo.get("latitude")
            longitude = geo.get("longitude")
            if latitude is None or longitude is None:
                return _error_response(
                    "geolocation_failed",
                    f"Geocoding response missing coordinates for: {location!r}",
                    location=location,
                    date_input=date_input,
                    parsed_date=parsed_date,
                )

            archive_params = {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": parsed_date,
                "end_date": parsed_date,
                "daily": _DAILY_FIELDS,
            }
            weather_payload = await _fetch_json(client, ARCHIVE_URL, archive_params)
    except httpx.TimeoutException:
        logger.warning(
            "Open-Meteo request timed out",
            extra={"location": location, "date": parsed_date},
        )
        return _error_response(
            "timeout",
            "Open-Meteo request timed out.",
            location=location,
            date_input=date_input,
            parsed_date=parsed_date,
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Open-Meteo HTTP error",
            extra={
                "location": location,
                "date": parsed_date,
                "status_code": exc.response.status_code,
            },
        )
        return _error_response(
            "http_error",
            f"Open-Meteo HTTP {exc.response.status_code}.",
            location=location,
            date_input=date_input,
            parsed_date=parsed_date,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "Open-Meteo network error",
            extra={"location": location, "date": parsed_date, "error": str(exc)},
        )
        return _error_response(
            "network_error",
            f"Network error contacting Open-Meteo: {exc}",
            location=location,
            date_input=date_input,
            parsed_date=parsed_date,
        )
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "Open-Meteo invalid JSON payload",
            extra={"location": location, "date": parsed_date, "error": str(exc)},
        )
        return _error_response(
            "invalid_response",
            f"Invalid Open-Meteo response: {exc}",
            location=location,
            date_input=date_input,
            parsed_date=parsed_date,
        )

    daily = weather_payload.get("daily") or {}
    times = daily.get("time") or []
    precipitations = daily.get("precipitation_sum") or []
    winds = daily.get("windspeed_10m_max") or []

    if not times:
        return _error_response(
            "no_data",
            f"No historical weather data for {parsed_date}.",
            location=location,
            date_input=date_input,
            parsed_date=parsed_date,
        )

    precipitation_mm = float(precipitations[0]) if precipitations else 0.0
    wind_kmh = float(winds[0]) if winds else 0.0
    had_heavy_rain = precipitation_mm >= HEAVY_RAIN_MM
    had_strong_winds = wind_kmh > STRONG_WIND_KMH

    result = {
        "location_verified": _format_location_verified(geo),
        "date": parsed_date,
        "had_heavy_rain": had_heavy_rain,
        "had_strong_winds": had_strong_winds,
        "precipitation_mm": round(precipitation_mm, 1),
        "max_wind_kmh": round(wind_kmh, 1),
        "summary": _build_summary(precipitation_mm, wind_kmh),
        "source": "open-meteo",
    }

    logger.info(
        "Open-Meteo weather history retrieved",
        extra={
            "location_verified": result["location_verified"],
            "date": parsed_date,
            "had_heavy_rain": had_heavy_rain,
            "had_strong_winds": had_strong_winds,
        },
    )
    return result
