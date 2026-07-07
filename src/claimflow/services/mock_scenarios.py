"""Lightweight MockLLM scenario detection — no LangChain or agent imports."""

from __future__ import annotations

from enum import StrEnum

_STORM_KEYWORDS: tuple[str, ...] = ("tempestade", "chuva", "vendaval", "vento")
_FRAUD_KEYWORDS: tuple[str, ...] = ("fogo", "incêndio", "incendio", "queimou")


class MockScenario(StrEnum):
    """Deterministic demo scenarios selected by claim-text keywords."""

    STORM_CLAIM = "STORM_CLAIM"
    FRAUD_CLAIM = "FRAUD_CLAIM"
    AMBIGUOUS = "AMBIGUOUS"


_SCENARIO_DISPLAY: dict[MockScenario, dict[str, str]] = {
    MockScenario.STORM_CLAIM: {
        "label": "STORM",
        "title": "Legitimate Storm Claim",
        "expected_outcome": "AUTO-APPROVED (risk score ~0.15)",
    },
    MockScenario.FRAUD_CLAIM: {
        "label": "FRAUD",
        "title": "Obvious Fraud",
        "expected_outcome": "HUMAN_REVIEW → REJECTED (risk score ~0.88)",
    },
    MockScenario.AMBIGUOUS: {
        "label": "AMBIGUOUS",
        "title": "Ambiguous Case",
        "expected_outcome": "HUMAN_REVIEW (risk score ~0.65)",
    },
}


def detect_mock_scenario(text: str) -> tuple[MockScenario, str | None]:
    """Select a deterministic MockLLM scenario from claim text keywords.

    Priority: fraud keywords → storm keywords → ambiguous default.
    """
    lowered = text.lower()
    for keyword in _FRAUD_KEYWORDS:
        if keyword in lowered:
            return MockScenario.FRAUD_CLAIM, keyword
    for keyword in _STORM_KEYWORDS:
        if keyword in lowered:
            return MockScenario.STORM_CLAIM, keyword
    return MockScenario.AMBIGUOUS, None


def get_mock_scenario_info(text: str = "") -> dict[str, str | None]:
    """Return human-readable scenario metadata for UI and logging."""
    scenario, keyword = detect_mock_scenario(text)
    display = _SCENARIO_DISPLAY[scenario]
    return {
        "scenario": scenario.value,
        "label": display["label"],
        "title": display["title"],
        "keyword": keyword,
        "keyword_reason": (
            f"Matched keyword: '{keyword}'" if keyword else "No keyword match (default)"
        ),
        "expected_outcome": display["expected_outcome"],
    }
