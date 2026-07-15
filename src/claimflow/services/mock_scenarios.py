"""Lightweight MockLLM scenario detection and English demo payloads.

Scenario free-text defaults to English (hackathon default). Portuguese/Spanish
overlays are applied when the request language is ``pt`` / ``es``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from claimflow.core.i18n import Language, normalize_language

# Keyword detection remains multilingual so pt/es demo claim text still matches.
_STORM_KEYWORDS: tuple[str, ...] = (
    "tempestade",
    "chuva",
    "vendaval",
    "vento",
    "storm",
    "rain",
    "wind",
    "windstorm",
    "tormenta",
)
_FRAUD_KEYWORDS: tuple[str, ...] = (
    "fogo",
    "incêndio",
    "incendio",
    "queimou",
    "fire",
    "burned",
    "burnt",
    "kitchen caught fire",
)


class MockScenario(StrEnum):
    """Deterministic demo scenarios selected by claim-text keywords."""

    STORM_CLAIM = "STORM_CLAIM"
    FRAUD_CLAIM = "FRAUD_CLAIM"
    AMBIGUOUS = "AMBIGUOUS"


# Canonical English payloads used by MockLLM (hackathon default).
STORM_SCENARIO: dict[str, Any] = {
    "cliente_nome": "Maria Oliveira",
    "tipo_dano": "VENTO",
    "localizacao": "São Paulo, SP",
    "descricao_resumida": "Roof damaged by strong windstorm last night",
    "data_incidente": "2026-07-06",
    "tool_reasoning": (
        "MockLLM: report mentions wind/storm — "
        "weather verification required to validate the claim."
    ),
    "requires_tool_call": True,
    "tool_name": "get_weather_history",
    "tool_arguments": {"location": "São Paulo, SP", "date": "2026-07-06"},
    "fraud_risk_score": 0.15,
    "severity_score": 0.45,
    "justificativa_risco": (
        "MockLLM: wind-damage claim consistent with weather verification "
        "(heavy rain and strong winds confirmed). Visual analysis matches "
        "wind damage (consistency_score=0.9). Low fraud risk."
    ),
    "requires_human_review": False,
}

FRAUD_SCENARIO: dict[str, Any] = {
    "cliente_nome": "Carlos Silva",
    "tipo_dano": "FOGO",
    "localizacao": "Rio de Janeiro, RJ",
    "descricao_resumida": "Kitchen caught fire yesterday",
    "data_incidente": "2026-07-06",
    "tool_reasoning": (
        "MockLLM: domestic fire with no weather events mentioned — "
        "meteorological verification not required."
    ),
    "requires_tool_call": False,
    "tool_name": "none",
    "tool_arguments": {},
    "fraud_risk_score": 0.88,
    "severity_score": 0.70,
    "justificativa_risco": (
        "MockLLM: fire report contradicts visual analysis (water leak, "
        "consistency_score=0.1). Sunny conditions without wind reinforce "
        "the inconsistency. High fraud probability — escalate to human review."
    ),
    "requires_human_review": True,
}

AMBIGUOUS_SCENARIO: dict[str, Any] = {
    "cliente_nome": "João Santos",
    "tipo_dano": "OUTRO",
    "localizacao": "Belo Horizonte, MG",
    "descricao_resumida": "Property damage, I need help",
    "data_incidente": None,
    "tool_reasoning": (
        "MockLLM: vague report without location, date, or weather event — "
        "no external tool applicable."
    ),
    "requires_tool_call": False,
    "tool_name": "none",
    "tool_arguments": {},
    "fraud_risk_score": 0.65,
    "severity_score": 0.50,
    "justificativa_risco": (
        "MockLLM: insufficient report for automatic conclusion. "
        "Inconclusive visual analysis (consistency_score=0.5). "
        "Moderate weather. Human review required."
    ),
    "requires_human_review": True,
}

_SCENARIO_BY_TYPE: dict[MockScenario, dict[str, Any]] = {
    MockScenario.STORM_CLAIM: STORM_SCENARIO,
    MockScenario.FRAUD_CLAIM: FRAUD_SCENARIO,
    MockScenario.AMBIGUOUS: AMBIGUOUS_SCENARIO,
}

# Optional free-text overlays when UI/LLM language is not English.
_LOCALIZED_TEXT: dict[Language, dict[MockScenario, dict[str, str]]] = {
    "pt": {
        MockScenario.STORM_CLAIM: {
            "descricao_resumida": "Telhado danificado por vendaval forte ontem à noite",
            "tool_reasoning": (
                "MockLLM: relato menciona vendaval/tempestade — "
                "verificação climática obrigatória para validar o sinistro."
            ),
            "justificativa_risco": (
                "MockLLM: sinistro por vendaval coerente com verificação climática "
                "(chuva forte e ventos intensos confirmados). Análise visual consistente "
                "com dano por vento (consistency_score=0.9). Baixo risco de fraude."
            ),
        },
        MockScenario.FRAUD_CLAIM: {
            "descricao_resumida": "Cozinha pegou fogo ontem",
            "tool_reasoning": (
                "MockLLM: incêndio doméstico sem menção a eventos climáticos — "
                "verificação meteorológica não necessária."
            ),
            "justificativa_risco": (
                "MockLLM: relato de incêndio contradiz análise visual (vazamento de água, "
                "consistency_score=0.1). Condições climáticas ensolaradas sem vento reforçam "
                "inconsistência. Alta probabilidade de fraude — escalação para revisão humana."
            ),
        },
        MockScenario.AMBIGUOUS: {
            "descricao_resumida": "Dano na propriedade, preciso de ajuda",
            "tool_reasoning": (
                "MockLLM: relato vago sem localização, data ou evento climático — "
                "nenhuma ferramenta externa aplicável."
            ),
            "justificativa_risco": (
                "MockLLM: relato insuficiente para conclusão automática. "
                "Análise visual inconclusiva (consistency_score=0.5). "
                "Condições climáticas moderadas. Revisão humana necessária."
            ),
        },
    },
    "es": {
        MockScenario.STORM_CLAIM: {
            "descricao_resumida": "Techo dañado por fuertes vientos anoche",
            "tool_reasoning": (
                "MockLLM: el relato menciona viento/tormenta — "
                "verificación climática obligatoria para validar el siniestro."
            ),
            "justificativa_risco": (
                "MockLLM: siniestro por viento coherente con verificación climática "
                "(lluvia fuerte y vientos intensos confirmados). Análisis visual "
                "consistente con daño por viento (consistency_score=0.9). "
                "Bajo riesgo de fraude."
            ),
        },
        MockScenario.FRAUD_CLAIM: {
            "descricao_resumida": "La cocina se incendió ayer",
            "tool_reasoning": (
                "MockLLM: incendio doméstico sin eventos climáticos mencionados — "
                "verificación meteorológica no necesaria."
            ),
            "justificativa_risco": (
                "MockLLM: el relato de incendio contradice el análisis visual "
                "(fuga de agua, consistency_score=0.1). Condiciones soleadas sin viento "
                "refuerzan la inconsistencia. Alta probabilidad de fraude — escalar a "
                "revisión humana."
            ),
        },
        MockScenario.AMBIGUOUS: {
            "descricao_resumida": "Daño en la propiedad, necesito ayuda",
            "tool_reasoning": (
                "MockLLM: relato vago sin ubicación, fecha o evento climático — "
                "ninguna herramienta externa aplicable."
            ),
            "justificativa_risco": (
                "MockLLM: relato insuficiente para conclusión automática. "
                "Análisis visual inconclusivo (consistency_score=0.5). "
                "Condiciones climáticas moderadas. Se requiere revisión humana."
            ),
        },
    },
}

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


def get_mock_scenario_payload(
    scenario: MockScenario,
    language: str = "en",
) -> dict[str, Any]:
    """Return a scenario payload with free-text fields in the requested language."""
    lang = normalize_language(language)
    payload = dict(_SCENARIO_BY_TYPE[scenario])
    if lang != "en":
        payload.update(_LOCALIZED_TEXT.get(lang, {}).get(scenario, {}))
    return payload


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
