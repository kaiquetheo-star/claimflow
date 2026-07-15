"""Claimflow Autopilot — Enterprise Streamlit frontend for Track 4 Human-in-the-Loop."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

import requests
import streamlit as st

from claimflow.core.i18n import (
    DEFAULT_LANGUAGE,
    Language,
    get_available_languages,
    normalize_language,
    t,
)
from claimflow.services.mock_scenarios import get_mock_scenario_info

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001").rstrip("/")
API_BASE_URL = f"{BACKEND_URL}/api/v1"
SUBMIT_URL = f"{API_BASE_URL}/claims/submit"
HEALTH_URL = f"{API_BASE_URL}/health"
DECISION_URL_TEMPLATE = f"{API_BASE_URL}/review/{{claim_id}}/decision"
ANALYST_ID = "demo-analyst"
# Prefer CLAIMFLOW_API_KEY; fall back to API_KEY (same as backend Settings).
API_KEY = (
    os.getenv("CLAIMFLOW_API_KEY")
    or os.getenv("API_KEY")
    or "cf_hk_a8f3b2c19e4d5f60718293a4b5c6d7e8"
)


def _api_headers() -> dict[str, str]:
    """Headers for authenticated mutating API calls."""
    return {"X-API-Key": API_KEY}

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
FRAUD_HIGH_RISK_THRESHOLD = 0.7


def _lang() -> Language:
    """Return the currently selected UI language, defaulting to English."""
    return normalize_language(st.session_state.get("language", DEFAULT_LANGUAGE))


def _processing_steps(lang: Language) -> list[tuple[str, str, str]]:
    return [
        ("📥", t("receiving_data", lang), "intake"),
        ("🤖", t("extracting_text", lang), "triage"),
        ("👁️", t("analyzing_image", lang), "vision"),
        ("🌦️", t("verifying_weather", lang), "weather"),
        ("⚖️", t("calculating_risk", lang), "risk"),
    ]


def _demo_claims(lang: Language) -> dict[str, dict[str, str]]:
    """Return demo claim presets.

    Claim *bodies* default to English (hackathon). Labels/hints follow ``lang``.
    Localized bodies are provided for pt/es so keyword-based MockLLM detection
    still works when the UI language is switched.
    """
    bodies: dict[str, dict[Language, str]] = {
        "legitimate": {
            "en": (
                "Subject: Storm damage claim\n\n"
                "Hello, I am Ana Paula. Yesterday's storm in São Paulo caused a leak "
                "in my apartment roof. Heavy rain came through the covering and damaged "
                "the ceiling and living-room floor on 06/07/2026."
            ),
            "pt": (
                "Assunto: Sinistro por tempestade\n\n"
                "Olá, sou Ana Paula. A tempestade de ontem em São Paulo causou vazamento "
                "no telhado do meu apartamento. Chuva forte entrou pela cobertura e danificou "
                "o forro e o piso da sala em 06/07/2026."
            ),
            "es": (
                "Asunto: Siniestro por tormenta\n\n"
                "Hola, soy Ana Paula. La tormenta de ayer en São Paulo causó una filtración "
                "en el techo de mi apartamento. La lluvia fuerte dañó el cielo raso "
                "y el piso de la sala el 06/07/2026."
            ),
        },
        "fraud": {
            "en": (
                "Subject: Residential fire claim\n\n"
                "Good afternoon, I am Carlos Mendes. My apartment caught fire last night "
                "in São Paulo. The fire destroyed the kitchen and part of the living room. "
                "I urgently need compensation for the fire."
            ),
            "pt": (
                "Assunto: Sinistro residencial — incêndio\n\n"
                "Boa tarde, sou Carlos Mendes. Meu apartamento pegou fogo ontem à noite "
                "em São Paulo. O fogo destruiu a cozinha e parte da sala. "
                "Preciso de indenização urgente pelo incêndio."
            ),
            "es": (
                "Asunto: Siniestro residencial — incendio\n\n"
                "Buenas tardes, soy Carlos Mendes. Mi apartamento se incendió anoche "
                "en São Paulo. El fuego destruyó la cocina y parte de la sala. "
                "Necesito compensación urgente por el incendio."
            ),
        },
        "ambiguous": {
            "en": (
                "I need help with a problem at my house. "
                "Something happened and I need to resolve it with the insurance."
            ),
            "pt": (
                "Preciso de ajuda com um problema na minha casa. "
                "Algo aconteceu e preciso resolver com o seguro."
            ),
            "es": (
                "Necesito ayuda con un problema en mi casa. "
                "Algo ocurrió y necesito resolverlo con el seguro."
            ),
        },
    }
    return {
        "legitimate": {
            "label": t("example_storm", lang),
            "claim_id": "CLM-LEGIT-002",
            "text": bodies["legitimate"][lang],
            "hint": t("demo_hint_legit", lang),
        },
        "fraud": {
            "label": t("example_fraud", lang),
            "claim_id": "CLM-FRAUD-001",
            "text": bodies["fraud"][lang],
            "hint": t("demo_hint_fraud", lang),
        },
        "ambiguous": {
            "label": t("example_ambiguous", lang),
            "claim_id": "CLM-AMB-003",
            "text": bodies["ambiguous"][lang],
            "hint": t("demo_hint_ambiguous", lang),
        },
    }


logger = logging.getLogger("claimflow.frontend")


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "language": DEFAULT_LANGUAGE,
        "claim_id": "CLM-001",
        "claim_result": None,
        "claim_detail": None,
        "processing": False,
        "pending_submission": None,
        "human_decision": None,
        "analyst_override": False,
        "submit_error": None,
        "demo_mode": False,
        "demo_hint": "",
        "processing_started_at": None,
        "processing_elapsed": None,
        "node_timings": {},
        "submitted_image_bytes": None,
        "analyst_notes": "",
        "pending_confirmation": None,
        "audit_trail": [],
        "decision_history": [],
        "decision_receipt": None,
        "decision_error": None,
        "input_claim_id": "CLM-001",
        "input_raw_text": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }

        .main .block-container {
            padding-top: 1.5rem;
            max-width: 1400px;
        }

        .cf-header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
            border-radius: 12px;
            padding: 1.5rem 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            color: #ffffff;
        }
        .cf-header h1 {
            margin: 0;
            font-size: 1.75rem;
            font-weight: 700;
        }
        .cf-header p {
            margin: 0.35rem 0 0 0;
            color: #e2e8f0;
            font-size: 0.95rem;
        }
        .cf-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 1.25rem 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 1rem;
        }
        .cf-card-title {
            color: #1a1a2e;
            font-weight: 600;
            font-size: 1.05rem;
            margin-bottom: 0.75rem;
            border-bottom: 2px solid #FF6A00;
            padding-bottom: 0.5rem;
        }

        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 6px;
        }
        .status-dot.online { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
        .status-dot.offline { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

        .risk-high {
            border: 2px solid #ef4444;
            border-radius: 10px;
            padding: 1rem;
            background: #fef2f2;
        }
        .risk-low {
            border: 2px solid #22c55e;
            border-radius: 10px;
            padding: 1rem;
            background: #f0fdf4;
        }

        div[data-testid="stSidebar"] {
            background: #f8fafc;
            border-right: 1px solid #e2e8f0;
        }

        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #FF6A00 0%, #e55f00 100%);
            border: none;
            font-weight: 600;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .stButton > button[kind="primary"]:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(255, 106, 0, 0.35);
        }

        .approve-btn button {
            background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
            color: white !important;
            border: none !important;
            font-weight: 600 !important;
            width: 100%;
            padding: 0.75rem 1rem !important;
            transition: transform 0.15s ease;
        }
        .approve-btn button:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(22, 163, 74, 0.35);
        }
        .approve-btn button:disabled {
            background: #9ca3af !important;
            color: #f3f4f6 !important;
        }
        .reject-btn button {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
            color: white !important;
            border: none !important;
            font-weight: 600 !important;
            width: 100%;
            padding: 0.75rem 1rem !important;
            transition: transform 0.15s ease;
        }
        .reject-btn button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(220, 38, 38, 0.35);
        }

        .audit-entry {
            background: #f1f5f9;
            border-left: 3px solid #FF6A00;
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.5rem;
            border-radius: 0 6px 6px 0;
            font-size: 0.85rem;
        }

        .demo-mode-banner {
            background: linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%);
            border: 2px solid #FF6A00;
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 1.25rem;
            box-shadow: 0 2px 8px rgba(255, 106, 0, 0.15);
        }
        .demo-mode-banner h3 {
            margin: 0 0 0.5rem 0;
            color: #9a3412;
            font-size: 1.1rem;
        }
        .demo-mode-banner p {
            margin: 0.25rem 0;
            color: #7c2d12;
            font-size: 0.9rem;
        }

        .scenario-panel {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.75rem;
            margin-top: 0.5rem;
        }
        .scenario-panel .scenario-tag {
            display: inline-block;
            background: #FF6A00;
            color: white;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            margin-bottom: 0.5rem;
        }

        /* Suppress Streamlit's decorative cartoon/spinner media */
        div[data-testid="stSpinner"] img,
        .stSpinner img {
            display: none !important;
        }
        div[data-testid="stSpinner"] > div {
            border: 3px solid #e2e8f0;
            border-top-color: #FF6A00;
            border-radius: 50%;
            width: 28px;
            height: 28px;
            animation: cf-spin 0.8s linear infinite;
        }
        @keyframes cf-spin {
            to { transform: rotate(360deg); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    lang = _lang()
    st.markdown(
        f"""
        <div class="cf-header">
            <h1>{t("app_title", lang)}</h1>
            <p>{t("app_subtitle", lang)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=15, show_spinner=False)
def check_backend_health() -> bool:
    try:
        response = requests.get(HEALTH_URL, timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


@st.cache_data(ttl=15, show_spinner=False)
def fetch_health_status() -> dict[str, Any] | None:
    """Return parsed ``/health`` JSON or ``None`` when the backend is unreachable."""
    try:
        response = requests.get(HEALTH_URL, timeout=3)
        if response.status_code == 200:
            payload = response.json()
            return payload if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError):
        pass
    return None


def _render_mock_mode_banner() -> None:
    """Show a prominent banner when the backend runs in MockLLM demo mode."""
    lang = _lang()
    health = fetch_health_status()
    if not health or not health.get("mock_mode"):
        return

    qwen = (health.get("alibaba_cloud_services") or {}).get("qwen_cloud", {})
    qwen_ok = qwen.get("status") == "connected"
    connectivity_line = t("qwen_connected", lang) if qwen_ok else t("qwen_pending", lang)

    st.markdown(
        f"""
        <div class="demo-mode-banner">
            <h3>{t("demo_mode_active", lang)}</h3>
            <p>{t("demo_mode_desc", lang)}</p>
            <p>{connectivity_line}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_current_scenario_panel() -> None:
    """Show which MockLLM scenario will be selected from the current claim text."""
    lang = _lang()
    health = fetch_health_status()
    if not health or not health.get("mock_mode"):
        return

    claim_text = st.session_state.get("input_raw_text", "") or ""
    info = get_mock_scenario_info(claim_text)

    st.markdown(f"### {t('current_scenario', lang)}")
    st.markdown(
        f"""
        <div class="scenario-panel">
            <span class="scenario-tag">{info['label']}</span>
            <div><strong>{info['title']}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(t("scenario_why", lang, info["keyword_reason"]))
    st.caption(t("scenario_expected", lang, info["expected_outcome"]))


def _render_sidebar() -> None:
    with st.sidebar:
        lang_options = get_available_languages()
        current_idx = next(
            (
                i
                for i, (code, _) in enumerate(lang_options)
                if code == st.session_state.get("language", DEFAULT_LANGUAGE)
            ),
            0,
        )
        selected = st.selectbox(
            t("language_selector", st.session_state.get("language", DEFAULT_LANGUAGE)),
            options=[code for code, _ in lang_options],
            format_func=lambda code: dict(lang_options)[code],
            index=current_idx,
        )
        if selected != st.session_state.get("language", DEFAULT_LANGUAGE):
            st.session_state.language = normalize_language(selected)
            st.rerun()

        lang = _lang()

        backend_ok = check_backend_health()
        dot_class = "online" if backend_ok else "offline"
        status_label = t("operational", lang) if backend_ok else t("offline", lang)

        st.markdown(f"### {t('control_panel', lang)}")
        st.markdown(
            f'<span class="status-dot {dot_class}"></span> '
            f'**{t("system_status", lang)}:** {status_label}',
            unsafe_allow_html=True,
        )
        st.caption(t("backend_caption", lang))
        st.divider()

        st.metric(t("todays_claims", lang), "47", delta="12 today", delta_color="normal")
        st.caption(t("claims_caption", lang))
        st.metric(
            t("fraud_detection_rate", lang),
            "23%",
            delta="↑ 3% vs last week",
            delta_color="inverse",
        )
        st.caption(t("fraud_rate_caption", lang))
        st.divider()

        st.session_state.demo_mode = st.toggle(
            t("demo_mode_label", lang),
            value=st.session_state.demo_mode,
            help=t("demo_mode_help", lang),
        )

        if st.session_state.demo_mode:
            st.markdown(f"**{t('quick_load_examples', lang)}**")
            demo_claims = _demo_claims(lang)
            for key, example in demo_claims.items():
                if st.button(example["label"], key=f"demo_{key}", width="stretch"):
                    st.session_state.input_claim_id = example["claim_id"]
                    st.session_state.input_raw_text = example["text"]
                    st.session_state.demo_hint = example["hint"]
                    st.session_state.claim_id = example["claim_id"]
                    st.rerun()
            if st.session_state.demo_hint:
                st.info(st.session_state.demo_hint)

        st.divider()

        _render_current_scenario_panel()

        st.divider()
        st.markdown(f"### {t('decision_history', lang)}")
        history = st.session_state.decision_history
        if history:
            for entry in history[:5]:
                icon = "✅" if entry["decision"] == "APPROVED" else "❌"
                notes_preview = entry.get("notes", "")
                if len(notes_preview) > 60:
                    notes_preview = f"{notes_preview[:57]}..."
                st.caption(
                    f"{icon} **{entry['claim_id']}** · {entry['timestamp']}\n\n"
                    f"{notes_preview or t('no_notes', lang)}"
                )
        else:
            st.caption(t("no_decisions_yet", lang))


def _validate_image(uploaded_file: Any, lang: Language) -> str | None:
    if uploaded_file is None:
        return None
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return t("upload_type_error", lang)
    return None


def _submit_claim_worker(
    claim_id: str,
    raw_input_text: str,
    language: str,
    image_bytes: bytes | None,
    image_filename: str | None,
    image_content_type: str | None,
    result_holder: dict[str, Any],
) -> None:
    lang = normalize_language(language)
    try:
        data = {
            "claim_id": claim_id,
            "raw_input_text": raw_input_text,
            "language": lang,
        }
        files = None
        if image_bytes and image_filename:
            content_type = image_content_type or "image/jpeg"
            files = {"image": (image_filename, image_bytes, content_type)}

        response = requests.post(
            SUBMIT_URL,
            data=data,
            files=files,
            headers=_api_headers(),
            timeout=300,
        )

        if response.status_code >= 400:
            if response.content:
                detail = response.json().get("detail", response.text)
            else:
                detail = response.text
            result_holder["error"] = str(detail)
            return

        result_holder["data"] = response.json()
    except requests.ConnectionError:
        result_holder["error"] = t("backend_unreachable", lang)
    except requests.Timeout:
        result_holder["error"] = t("timeout_error", lang)
    except requests.RequestException as exc:
        result_holder["error"] = t("network_error", lang, exc)


def fetch_claim_detail(claim_id: str) -> dict[str, Any] | None:
    try:
        response = requests.get(f"{API_BASE_URL}/review/{claim_id}", timeout=15)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        pass
    return None


def submit_review_decision_api(
    claim_id: str,
    decision: str,
    analyst_notes: str,
    lang: Language,
) -> tuple[bool, dict[str, Any] | str]:
    """POST human decision to the review API. Returns (success, response_or_error)."""
    url = DECISION_URL_TEMPLATE.format(claim_id=claim_id)
    payload = {
        "decision": decision.lower(),
        "analyst_notes": analyst_notes,
        "analyst_id": ANALYST_ID,
    }

    try:
        response = requests.post(url, json=payload, headers=_api_headers(), timeout=15)
    except requests.ConnectionError:
        return False, t("backend_unreachable", lang)
    except requests.Timeout:
        return False, t("timeout_error", lang)
    except requests.RequestException as exc:
        return False, t("network_error", lang, exc)

    if response.status_code == 404:
        return False, t("claim_not_found", lang)
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text) if response.content else response.text
        if response.status_code == 409 and "already recorded" in str(detail).lower():
            return False, t("decision_already_api", lang)
        return False, str(detail)

    return True, response.json()


def _human_review_status_label(result: dict[str, Any], human_decision: str | None) -> str:
    if human_decision:
        return human_decision
    agent_status = str(result.get("status", "PENDING")).upper()
    if agent_status == "HUMAN_REVIEW" or result.get("awaiting_human_decision"):
        return "PENDING REVIEW"
    return agent_status


def _is_awaiting_human_decision(result: dict[str, Any], detail: dict[str, Any] | None) -> bool:
    """True when LangGraph is paused at interrupt_before=['human_review']."""
    if result.get("awaiting_human_decision") or result.get("graph_interrupted"):
        return True
    payload = (detail or {}).get("payload") or {}
    if payload.get("awaiting_human_decision") or payload.get("graph_interrupted"):
        return True
    return str(result.get("status", "")).upper() == "HUMAN_REVIEW"


def _render_decision_receipt(receipt: dict[str, Any], lang: Language) -> None:
    st.markdown(f"#### 🧾 {t('decision_receipt', lang)}")
    st.markdown(
        f"""
        <div class="cf-card" style="border-left: 4px solid #FF6A00;">
            <strong>{t("receipt_claim", lang)}</strong> {receipt.get("claim_id", "—")}<br/>
            <strong>{t("receipt_decision", lang)}</strong> {receipt.get("decision", "—")}<br/>
            <strong>{t("receipt_analyst", lang)}</strong> {receipt.get("analyst_id", ANALYST_ID)}<br/>
            <strong>{t("receipt_recorded", lang)}</strong> {receipt.get("timestamp", "—")}<br/>
            <strong>{t("receipt_notes", lang)}</strong> {receipt.get("notes") or t("no_notes", lang)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _full_payload(result: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    if detail and detail.get("payload"):
        merged = dict(detail["payload"])
        merged.update({k: v for k, v in result.items() if v is not None})
        return merged
    return result


def _weather_verification_label(payload: dict[str, Any], lang: Language) -> str:
    weather = payload.get("weather_verification")
    extracted = payload.get("extracted_data") or {}

    if not weather:
        return t("not_checked", lang)

    if weather.get("error"):
        return t("mismatch", lang)

    damage_type = str(extracted.get("tipo_dano", "")).upper()
    had_rain = bool(weather.get("had_heavy_rain"))
    had_wind = bool(weather.get("had_strong_winds"))

    if damage_type == "AGUA" and had_rain:
        return t("match", lang)
    if damage_type == "VENTO" and had_wind:
        return t("match", lang)
    if damage_type in {"AGUA", "VENTO"} and not had_rain and not had_wind:
        return t("mismatch", lang)
    if damage_type == "FOGO" and (had_rain or had_wind):
        return t("mismatch", lang)

    return t("match", lang)


def _collect_inconsistencies(
    result: dict[str, Any], detail: dict[str, Any] | None, lang: Language
) -> list[str]:
    inconsistencies: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            inconsistencies.append(cleaned)

    image_analysis = result.get("image_analysis") or {}
    for item in image_analysis.get("inconsistencies") or []:
        _add(f"❌ {item}")

    risk_assessment = result.get("risk_assessment") or {}
    for penalty in risk_assessment.get("fail_closed_penalties") or []:
        _add(f"❌ {penalty}")

    justification = risk_assessment.get("justificativa_risco")
    if justification and result.get("fraud_risk_score", 0) > FRAUD_HIGH_RISK_THRESHOLD:
        _add(f"❌ {justification}")

    payload = _full_payload(result, detail)
    weather = payload.get("weather_verification") or {}
    if weather.get("error"):
        _add(t("weather_failed", lang, weather.get("message", weather.get("error"))))
    elif weather and _weather_verification_label(payload, lang) == t("mismatch", lang):
        summary = weather.get("summary", "Weather data does not support the reported incident.")
        _add(t("weather_mismatch", lang, summary))

    if not (result.get("extracted_data") or {}):
        _add(t("reason_empty_extraction", lang))

    if result.get("consistency_score") is not None:
        score = float(result["consistency_score"])
        if score < 0.5:
            _add(t("low_consistency", lang))

    return inconsistencies


def _render_data_quality_warnings(
    result: dict[str, Any], detail: dict[str, Any] | None, lang: Language
) -> None:
    payload = _full_payload(result, detail)

    if not (result.get("extracted_data") or {}):
        st.warning(t("insufficient_data", lang), icon="⚠️")

    had_image = bool(st.session_state.submitted_image_bytes) or bool(payload.get("image_path"))
    if had_image and not result.get("image_analysis"):
        st.warning(t("image_unavailable", lang), icon="👁️")

    raw_input = payload.get("raw_input", "")
    weather_keywords = ("chuva", "tempestade", "vento", "storm", "rain")
    mentions_weather = any(k in raw_input.lower() for k in weather_keywords)
    if mentions_weather and not payload.get("weather_verification"):
        st.warning(t("weather_unavailable", lang), icon="🌦️")


def _run_processing_flow(submission: dict[str, Any]) -> None:
    lang = normalize_language(submission.get("language"))
    result_holder: dict[str, Any] = {"data": None, "error": None}
    start_time = time.time()
    node_timings: dict[str, float] = {}

    worker = threading.Thread(
        target=_submit_claim_worker,
        kwargs={
            "claim_id": submission["claim_id"],
            "raw_input_text": submission["raw_input_text"],
            "language": lang,
            "image_bytes": submission.get("image_bytes"),
            "image_filename": submission.get("image_filename"),
            "image_content_type": submission.get("image_content_type"),
            "result_holder": result_holder,
        },
        daemon=True,
    )
    worker.start()

    with st.status(t("pipeline_status", lang), expanded=True) as status:
        st.write(f"📡 **{t('receiving_data', lang)}**")
        progress = st.progress(0, text=t("pipeline_status", lang))
        steps = _processing_steps(lang)
        total = len(steps)

        for index, (emoji, label, node_key) in enumerate(steps):
            step_start = time.time()
            if worker.is_alive() or index == 0:
                time.sleep(1.0)
            node_timings[node_key] = round(time.time() - step_start, 2)
            st.write(f"{emoji} **{label}** — _{node_timings[node_key]:.1f}s_")
            progress.progress(
                int((index + 1) / total * 100),
                text=f"{label} ({index + 1}/{total})",
            )

        worker.join(timeout=300)
        elapsed = round(time.time() - start_time, 2)

        if result_holder.get("error"):
            progress.progress(100, text=t("pipeline_complete", lang, elapsed))
            status.update(
                label=str(result_holder["error"]),
                state="error",
                expanded=True,
            )
        else:
            progress.progress(100, text=t("pipeline_complete", lang, elapsed))
            status.update(
                label=t("pipeline_complete", lang, elapsed),
                state="complete",
                expanded=False,
            )
    st.session_state.processing_elapsed = round(time.time() - start_time, 2)
    st.session_state.node_timings = node_timings

    if result_holder.get("error"):
        st.session_state.submit_error = result_holder["error"]
        st.session_state.claim_result = None
        st.session_state.claim_detail = None
    elif result_holder.get("data"):
        claim_result = result_holder["data"]
        st.session_state.claim_result = claim_result
        st.session_state.claim_id = claim_result.get("claim_id", submission["claim_id"])
        st.session_state.claim_detail = fetch_claim_detail(st.session_state.claim_id)
        st.session_state.submit_error = None
        st.session_state.human_decision = None
        st.session_state.pending_confirmation = None

    st.session_state.processing = False
    st.session_state.pending_submission = None


def _risk_delta(fraud_score: float) -> tuple[str, str]:
    pct = fraud_score * 100
    if fraud_score > FRAUD_HIGH_RISK_THRESHOLD:
        return f"{pct:.0f}%", "inverse"
    if fraud_score > 0.4:
        return f"{pct:.0f}%", "off"
    return f"{pct:.0f}%", "normal"


def _render_result_card(result: dict[str, Any], detail: dict[str, Any] | None) -> None:
    lang = _lang()
    fraud_score = float(result.get("fraud_risk_score", 0.0))
    is_high_risk = fraud_score > FRAUD_HIGH_RISK_THRESHOLD
    inconsistencies = _collect_inconsistencies(result, detail, lang)
    payload = _full_payload(result, detail)

    _render_data_quality_warnings(result, detail, lang)

    st.markdown(
        f'<div class="cf-card"><div class="cf-card-title">{t("risk_assessment_title", lang)}</div>',
        unsafe_allow_html=True,
    )

    if is_high_risk:
        st.markdown('<div class="risk-high">', unsafe_allow_html=True)
        st.error(f"### {t('high_risk_title', lang)}")
        if inconsistencies:
            st.markdown(f"**{t('high_risk_desc', lang)}**")
            for item in inconsistencies:
                st.markdown(f"- {item}")
        else:
            st.markdown(t("flagged_for_review", lang))
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="risk-low">', unsafe_allow_html=True)
        st.success(f"### {t('low_risk_title', lang)}")
        st.markdown(t("low_risk_desc", lang))
        st.markdown("</div>", unsafe_allow_html=True)

    metric_main, metric_side = st.columns([2, 1])
    fraud_delta, delta_color = _risk_delta(fraud_score)
    consistency = result.get("consistency_score")
    weather_label = _weather_verification_label(payload, lang)

    with metric_main:
        st.metric(
            t("fraud_risk_score", lang),
            f"{fraud_score * 100:.0f}%",
            delta=fraud_delta,
            delta_color=delta_color,  # type: ignore[arg-type]
            help="LLM-assessed probability of fraudulent intent (0–100%).",
        )
        st.caption(f"🔍 {t('higher_scores_note', lang)}")

    with metric_side:
        st.metric(
            t("consistency_score", lang),
            f"{float(consistency) * 100:.0f}%" if consistency is not None else "N/A",
            help="Text-vs-image damage type alignment score.",
        )
        st.metric(
            t("weather_verification", lang),
            weather_label,
            help="Open-Meteo historical verification against reported incident.",
        )
        if st.session_state.processing_elapsed:
            st.metric(t("processing_time", lang), f"{st.session_state.processing_elapsed:.1f}s")

    if st.session_state.submitted_image_bytes:
        st.markdown(f"**{t('evidence_image', lang)}**")
        st.image(
            st.session_state.submitted_image_bytes,
            caption=t("damage_photo_caption", lang, result.get("claim_id", "")),
            width="stretch",
        )

    st.markdown("</div>", unsafe_allow_html=True)
    _render_technical_details(result, detail, lang)


def _render_technical_details(
    result: dict[str, Any], detail: dict[str, Any] | None, lang: Language
) -> None:
    payload = _full_payload(result, detail)
    tools_called: list[str] = []
    if payload.get("image_analysis"):
        tools_called.append("Qwen-VL image analysis")
    if payload.get("weather_verification"):
        tools_called.append("Open-Meteo weather verification")
    for tool in payload.get("tool_calls_made") or []:
        if tool not in tools_called:
            tools_called.append(tool)

    with st.expander(t("technical_details", lang), expanded=False):
        st.markdown(f"**{t('tools_invoked', lang)}**")
        if tools_called:
            for tool in tools_called:
                st.markdown(f"- `{tool}`")
        else:
            st.caption(t("no_tools", lang))

        if st.session_state.node_timings:
            st.markdown(f"**{t('node_timing', lang)}**")
            for node, duration in st.session_state.node_timings.items():
                st.markdown(f"- `{node}`: {duration}s")

        st.markdown(f"**{t('raw_api_response', lang)}**")
        st.json(result)
        if detail:
            st.markdown(f"**{t('persisted_snapshot', lang)}**")
            st.json(detail)


def _record_decision(claim_id: str, decision: str, notes: str, lang: Language) -> bool:
    with st.status(t("recording_decision", lang), expanded=True) as status:
        st.write(t("recording_decision", lang))
        success, result = submit_review_decision_api(claim_id, decision, notes, lang)
        if not success:
            status.update(label=str(result), state="error", expanded=True)
            st.session_state.decision_error = str(result)
            st.error(str(result))
            return False
        status.update(label=t("decision_toast", lang), state="complete", expanded=False)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    api_decided_at = result.get("decided_at")
    if api_decided_at:
        timestamp = str(api_decided_at).replace("T", " ")[:19]

    receipt = {
        "timestamp": timestamp,
        "claim_id": claim_id,
        "decision": result.get("status", decision),
        "notes": notes or result.get("reviewer_note") or t("no_notes", lang),
        "analyst_id": result.get("analyst_id", ANALYST_ID),
        "api_response": result,
    }
    entry = {
        "timestamp": timestamp,
        "claim_id": claim_id,
        "decision": receipt["decision"],
        "notes": receipt["notes"],
        "analyst": receipt["analyst_id"],
    }

    st.session_state.decision_receipt = receipt
    st.session_state.decision_history.insert(0, entry)
    st.session_state.audit_trail.insert(0, entry)
    st.session_state.human_decision = receipt["decision"]
    st.session_state.pending_confirmation = None
    st.session_state.decision_error = None

    if st.session_state.claim_result:
        st.session_state.claim_result["status"] = receipt["decision"]
        st.session_state.claim_result["awaiting_human_decision"] = False
        st.session_state.claim_result["graph_interrupted"] = False
    if st.session_state.claim_detail:
        st.session_state.claim_detail["status"] = receipt["decision"]
        payload = st.session_state.claim_detail.get("payload")
        if isinstance(payload, dict):
            payload["awaiting_human_decision"] = False
            payload["graph_interrupted"] = False

    logger.info("Human analyst decision recorded via API", extra=entry)
    st.toast(t("decision_toast", lang), icon="✅")
    return True


def _reset_demo_decision_state(lang: Language) -> None:
    st.session_state.human_decision = None
    st.session_state.decision_receipt = None
    st.session_state.decision_error = None
    st.session_state.pending_confirmation = None
    st.session_state.analyst_notes = ""
    st.session_state.analyst_override = False
    st.toast(t("reset_toast", lang), icon="🔄")


def _render_human_actions(result: dict[str, Any]) -> None:
    lang = _lang()
    fraud_score = float(result.get("fraud_risk_score", 0.0))
    is_low_risk = fraud_score <= FRAUD_HIGH_RISK_THRESHOLD
    claim_id = result.get("claim_id", st.session_state.claim_id)
    decision_made = bool(st.session_state.human_decision or st.session_state.decision_receipt)
    status_label = _human_review_status_label(result, st.session_state.human_decision)
    awaiting = _is_awaiting_human_decision(result, st.session_state.claim_detail)

    st.markdown(
        f'<div class="cf-card"><div class="cf-card-title">{t("hitl_title", lang)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(t("hitl_caption", lang))

    status_color = {
        "APPROVED": "green",
        "REJECTED": "red",
        "PENDING REVIEW": "orange",
    }.get(status_label, "blue")
    st.markdown(f"**{t('current_status', lang)}** :{status_color}[{status_label}]")

    if awaiting and not decision_made:
        st.warning(t("waiting_human", lang))

    if st.session_state.decision_error and not decision_made:
        st.error(st.session_state.decision_error)

    if decision_made:
        st.info(t("decision_already_recorded", lang))
        if st.session_state.decision_receipt:
            _render_decision_receipt(st.session_state.decision_receipt, lang)
        if st.button(t("reset_demo", lang), width="stretch", key="reset_demo_decision"):
            _reset_demo_decision_state(lang)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not awaiting and not decision_made:
        st.caption(t("auto_finished_caption", lang))
        st.markdown("</div>", unsafe_allow_html=True)
        return

    with st.form("hitl_decision_form", border=False, clear_on_submit=False):
        notes = st.text_area(
            t("analyst_notes_label", lang),
            value=st.session_state.analyst_notes,
            height=100,
            placeholder=t("analyst_notes_placeholder", lang),
        )

        override = st.session_state.analyst_override
        if not is_low_risk:
            override = st.checkbox(
                t("analyst_override", lang),
                value=st.session_state.analyst_override,
                help=t("analyst_override_help", lang),
            )

        approve_enabled = is_low_risk or override
        action_cols = st.columns(2)
        with action_cols[0]:
            st.markdown('<div class="approve-btn">', unsafe_allow_html=True)
            approve_clicked = st.form_submit_button(
                t("approve_button", lang),
                disabled=not approve_enabled,
                width="stretch",
            )
            st.markdown("</div>", unsafe_allow_html=True)
        with action_cols[1]:
            st.markdown('<div class="reject-btn">', unsafe_allow_html=True)
            reject_clicked = st.form_submit_button(
                t("reject_button", lang),
                width="stretch",
            )
            st.markdown("</div>", unsafe_allow_html=True)

    if approve_clicked or reject_clicked:
        st.session_state.analyst_notes = notes
        st.session_state.analyst_override = override
        st.session_state.pending_confirmation = (
            "APPROVED" if approve_clicked else "REJECTED"
        )

    pending = st.session_state.pending_confirmation
    if pending:
        st.warning(t("confirm_decision", lang, claim_id, pending))
        confirm_cols = st.columns(2)
        with confirm_cols[0]:
            if st.button(
                t("yes_confirm", lang),
                type="primary",
                width="stretch",
                key="confirm_hitl_yes",
            ) and _record_decision(claim_id, pending, st.session_state.analyst_notes, lang):
                st.success(t("decision_success", lang, claim_id, pending))
                st.rerun()
        with confirm_cols[1]:
            if st.button(t("cancel", lang), width="stretch", key="confirm_hitl_cancel"):
                st.session_state.pending_confirmation = None
                st.rerun()

    if st.session_state.audit_trail:
        st.markdown(f"**{t('audit_trail', lang)}**")
        for entry in st.session_state.audit_trail[:5]:
            st.markdown(
                f'<div class="audit-entry">'
                f'<strong>{entry["timestamp"]}</strong> · {entry["claim_id"]} · '
                f'<strong>{entry["decision"]}</strong><br/>'
                f'{entry["notes"]}'
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)


def _handle_submit(
    claim_id: str,
    raw_input_text: str,
    uploaded_image: Any,
) -> None:
    lang = _lang()
    if not check_backend_health():
        st.error(t("backend_unreachable", lang))
        return
    if not raw_input_text or not raw_input_text.strip():
        st.error(t("empty_description_error", lang))
        return

    image_error = _validate_image(uploaded_image, lang)
    if image_error:
        st.error(image_error)
        return

    image_bytes = None
    image_filename = None
    image_content_type = None

    if uploaded_image is not None:
        image_bytes = uploaded_image.getvalue()
        if not image_bytes:
            st.error(t("upload_failed", lang))
            return
        image_filename = uploaded_image.name
        image_content_type = uploaded_image.type

    st.session_state.claim_id = claim_id.strip() or "CLM-001"
    st.session_state.submitted_image_bytes = image_bytes
    st.session_state.pending_submission = {
        "claim_id": st.session_state.claim_id,
        "raw_input_text": raw_input_text.strip(),
        "language": lang,
        "image_bytes": image_bytes,
        "image_filename": image_filename,
        "image_content_type": image_content_type,
    }
    st.session_state.processing = True
    st.session_state.processing_started_at = time.time()
    st.session_state.submit_error = None
    st.session_state.human_decision = None
    st.session_state.analyst_override = False
    st.session_state.analyst_notes = ""
    st.session_state.pending_confirmation = None
    st.session_state.decision_receipt = None
    st.session_state.decision_error = None
    st.rerun()


def _render_submission_form() -> None:
    lang = _lang()
    processing = bool(st.session_state.processing)

    st.markdown(
        f'<div class="cf-card"><div class="cf-card-title">{t("customer_portal_title", lang)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(t("customer_portal_caption", lang))

    if processing:
        st.info(t("pipeline_status", lang))

    # Batch inputs: typing does not rerun the app until form submit.
    with st.form("claim_submission_form", border=False, clear_on_submit=False):
        claim_id = st.text_input(
            t("claim_id_label", lang),
            key="input_claim_id",
            disabled=processing,
        )
        raw_input_text = st.text_area(
            t("claim_text_label", lang),
            height=160,
            placeholder=t("claim_text_placeholder", lang),
            key="input_raw_text",
            disabled=processing,
        )
        uploaded_image = st.file_uploader(
            t("upload_label", lang),
            type=["jpg", "jpeg", "png"],
            key="input_image",
            disabled=processing,
        )
        submitted = st.form_submit_button(
            t("submit_button", lang),
            type="primary",
            width="stretch",
            disabled=processing,
        )

    if submitted and not processing:
        _handle_submit(claim_id, raw_input_text, uploaded_image)

    st.markdown("</div>", unsafe_allow_html=True)


def _render_analyst_panel() -> None:
    lang = _lang()
    st.markdown(
        f'<div class="cf-card"><div class="cf-card-title">{t("analyst_panel_title", lang)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(t("analyst_panel_caption", lang))

    if st.session_state.processing and st.session_state.pending_submission:
        _run_processing_flow(st.session_state.pending_submission)

    if st.session_state.claim_result:
        _render_result_card(st.session_state.claim_result, st.session_state.claim_detail)
        _render_human_actions(st.session_state.claim_result)
    elif st.session_state.submit_error:
        st.error(st.session_state.submit_error)
    elif not st.session_state.processing:
        st.markdown(f"**{t('awaiting_submission', lang)}**\n\n{t('awaiting_submission_details', lang)}")

    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title="Claimflow Autopilot",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_session_state()
    _inject_styles()
    _render_sidebar()
    _render_header()
    _render_mock_mode_banner()

    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        _render_submission_form()

    with right_col:
        _render_analyst_panel()


if __name__ == "__main__":
    main()
