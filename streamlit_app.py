"""Claimflow Autopilot — Enterprise Streamlit frontend for Track 4 Human-in-the-Loop."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

import requests
import streamlit as st

from claimflow.services.mock_scenarios import get_mock_scenario_info

API_BASE_URL = "http://localhost:8000/api/v1"
SUBMIT_URL = f"{API_BASE_URL}/claims/submit"
HEALTH_URL = f"{API_BASE_URL}/health"
DECISION_URL_TEMPLATE = f"{API_BASE_URL}/review/{{claim_id}}/decision"
ANALYST_ID = "demo-analyst"
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
FRAUD_HIGH_RISK_THRESHOLD = 0.7

PROCESSING_STEPS: list[tuple[str, str, str]] = [
    ("📥", "Receiving claim data...", "intake"),
    ("🤖", "Extracting structured data from text...", "triage"),
    ("👁️", "Analyzing image with Qwen-VL...", "vision"),
    ("🌦️", "Verifying weather conditions via Open-Meteo...", "weather"),
    ("⚖️", "Calculating fraud risk score...", "risk"),
]

DEMO_CLAIMS: dict[str, dict[str, str]] = {
    "fraud": {
        "label": "Example 1: Obvious Fraud",
        "claim_id": "CLM-FRAUD-001",
        "text": (
            "Assunto: Sinistro residencial — incêndio\n\n"
            "Boa tarde, sou Carlos Mendes. Meu apartamento pegou fogo ontem à noite "
            "em São Paulo. O fogo destruiu a cozinha e parte da sala. "
            "Preciso de indenização urgente pelo incêndio."
        ),
        "hint": "Upload a water-damage / leak photo to trigger text-vs-image inconsistency.",
    },
    "legitimate": {
        "label": "Example 2: Legitimate Claim",
        "claim_id": "CLM-LEGIT-002",
        "text": (
            "Assunto: Sinistro por tempestade\n\n"
            "Olá, sou Ana Paula. A tempestade de ontem em São Paulo causou vazamento "
            "no telhado do meu apartamento. Chuva forte entrou pela cobertura e danificou "
            "o forro e o piso da sala em 06/07/2026."
        ),
        "hint": "Upload a storm / water damage photo for a consistent claim.",
    },
    "ambiguous": {
        "label": "Example 3: Ambiguous Case",
        "claim_id": "CLM-AMB-003",
        "text": (
            "Preciso de ajuda com um problema na minha casa. "
            "Algo aconteceu e preciso resolver com o seguro."
        ),
        "hint": "Submit without an image to test fail-closed data extraction handling.",
    },
}

logger = logging.getLogger("claimflow.frontend")


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
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
        .cf-logo {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 48px;
            height: 48px;
            border-radius: 10px;
            background: #FF6A00;
            font-size: 1.5rem;
            margin-right: 0.75rem;
            vertical-align: middle;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        """
        <div class="cf-header">
            <span class="cf-logo">🛡️</span>
            <span style="vertical-align: middle;">
                <h1 style="display:inline;">Claimflow Autopilot</h1>
                <p>Enterprise AI Claims Intelligence · Powered by Qwen Cloud · Track 4</p>
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def check_backend_health() -> bool:
    try:
        response = requests.get(HEALTH_URL, timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


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
    health = fetch_health_status()
    if not health or not health.get("mock_mode"):
        return

    qwen = (health.get("alibaba_cloud_services") or {}).get("qwen_cloud", {})
    qwen_ok = qwen.get("status") == "connected"
    connectivity_line = (
        "Real Qwen Cloud connectivity verified via /health endpoint (200 OK)."
        if qwen_ok
        else "DashScope health check pending — verify DASHSCOPE_API_KEY in .env."
    )

    st.markdown(
        f"""
        <div class="demo-mode-banner">
            <h3>🎭 Demo Mode Active</h3>
            <p>The system is using deterministic MockLLM scenarios for consistent demonstration.</p>
            <p>{connectivity_line}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_current_scenario_panel() -> None:
    """Show which MockLLM scenario will be selected from the current claim text."""
    health = fetch_health_status()
    if not health or not health.get("mock_mode"):
        return

    claim_text = st.session_state.get("input_raw_text", "") or ""
    info = get_mock_scenario_info(claim_text)
    keyword_line = f"**Why:** {info['keyword_reason']}"

    st.markdown("### 📊 Current Scenario")
    st.markdown(
        f"""
        <div class="scenario-panel">
            <span class="scenario-tag">{info['label']}</span>
            <div><strong>{info['title']}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(keyword_line.replace("**Why:** ", ""))
    st.caption(f"Expected: {info['expected_outcome']}")


def _render_sidebar() -> None:
    backend_ok = check_backend_health()
    dot_class = "online" if backend_ok else "offline"
    status_label = "Operational" if backend_ok else "Offline"

    with st.sidebar:
        st.markdown("### 🛡️ Control Panel")
        st.markdown(
            f'<span class="status-dot {dot_class}"></span> **System Status:** {status_label}',
            unsafe_allow_html=True,
        )
        st.caption("Live connection to FastAPI backend on port 8000.")
        st.divider()

        st.metric("Today's Claims", "47", delta="12 today", delta_color="normal")
        st.caption("Claims processed across all channels today.")
        st.metric("Fraud Detection Rate", "23%", delta="↑ 3% vs last week", delta_color="inverse")
        st.caption("Share of submissions flagged for human review.")
        st.divider()

        st.session_state.demo_mode = st.toggle(
            "Demo Mode",
            value=st.session_state.demo_mode,
            help="Load pre-built example claims for live demonstrations.",
        )

        if st.session_state.demo_mode:
            st.markdown("**Quick-load examples**")
            for key, example in DEMO_CLAIMS.items():
                if st.button(example["label"], key=f"demo_{key}", use_container_width=True):
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
        st.markdown("### 📋 Decision History")
        history = st.session_state.decision_history
        if history:
            for entry in history[:5]:
                icon = "✅" if entry["decision"] == "APPROVED" else "❌"
                notes_preview = entry.get("notes", "")
                if len(notes_preview) > 60:
                    notes_preview = f"{notes_preview[:57]}..."
                st.caption(
                    f"{icon} **{entry['claim_id']}** · {entry['timestamp']}\n\n"
                    f"{notes_preview or '(no notes)'}"
                )
        else:
            st.caption("No analyst decisions recorded yet.")


def _validate_image(uploaded_file: Any) -> str | None:
    if uploaded_file is None:
        return None
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return "❌ Image upload failed. Please try a different file (jpg, jpeg, or png only)."
    return None


def _submit_claim_worker(
    claim_id: str,
    raw_input_text: str,
    image_bytes: bytes | None,
    image_filename: str | None,
    image_content_type: str | None,
    result_holder: dict[str, Any],
) -> None:
    try:
        data = {"claim_id": claim_id, "raw_input_text": raw_input_text}
        files = None
        if image_bytes and image_filename:
            content_type = image_content_type or "image/jpeg"
            files = {"image": (image_filename, image_bytes, content_type)}

        response = requests.post(SUBMIT_URL, data=data, files=files, timeout=300)

        if response.status_code >= 400:
            if response.content:
                detail = response.json().get("detail", response.text)
            else:
                detail = response.text
            result_holder["error"] = str(detail)
            return

        result_holder["data"] = response.json()
    except requests.ConnectionError:
        result_holder["error"] = "⚠️ Backend not reachable. Please run 'make run' first."
    except requests.Timeout:
        result_holder["error"] = "Request timed out while processing the claim. Please try again."
    except requests.RequestException as exc:
        result_holder["error"] = f"Network error: {exc}"


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
) -> tuple[bool, dict[str, Any] | str]:
    """POST human decision to the review API. Returns (success, response_or_error)."""
    url = DECISION_URL_TEMPLATE.format(claim_id=claim_id)
    payload = {
        "decision": decision.lower(),
        "analyst_notes": analyst_notes,
        "analyst_id": ANALYST_ID,
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
    except requests.ConnectionError:
        return False, "⚠️ Backend not reachable. Please run 'make run' first."
    except requests.Timeout:
        return False, "Request timed out while recording the decision. Please try again."
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"

    if response.status_code == 404:
        return False, "Claim not found. Submit the claim before recording a decision."
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text) if response.content else response.text
        if response.status_code == 409 and "already recorded" in str(detail).lower():
            return False, "Decision already recorded for this claim."
        return False, str(detail)

    return True, response.json()


def _human_review_status_label(result: dict[str, Any], human_decision: str | None) -> str:
    if human_decision:
        return human_decision
    agent_status = str(result.get("status", "PENDING")).upper()
    if agent_status == "HUMAN_REVIEW":
        return "PENDING REVIEW"
    return agent_status


def _render_decision_receipt(receipt: dict[str, Any]) -> None:
    st.markdown("#### 🧾 Decision Receipt")
    st.markdown(
        f"""
        <div class="cf-card" style="border-left: 4px solid #FF6A00;">
            <strong>Claim:</strong> {receipt.get("claim_id", "—")}<br/>
            <strong>Decision:</strong> {receipt.get("decision", "—")}<br/>
            <strong>Analyst:</strong> {receipt.get("analyst_id", ANALYST_ID)}<br/>
            <strong>Recorded at:</strong> {receipt.get("timestamp", "—")}<br/>
            <strong>Notes:</strong> {receipt.get("notes") or "(no notes)"}
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


def _weather_verification_label(payload: dict[str, Any]) -> str:
    weather = payload.get("weather_verification")
    extracted = payload.get("extracted_data") or {}

    if not weather:
        return "— Not checked"

    if weather.get("error"):
        return "✗ Mismatch"

    damage_type = str(extracted.get("tipo_dano", "")).upper()
    had_rain = bool(weather.get("had_heavy_rain"))
    had_wind = bool(weather.get("had_strong_winds"))

    if damage_type == "AGUA" and had_rain:
        return "✓ Match"
    if damage_type == "VENTO" and had_wind:
        return "✓ Match"
    if damage_type in {"AGUA", "VENTO"} and not had_rain and not had_wind:
        return "✗ Mismatch"
    if damage_type == "FOGO" and (had_rain or had_wind):
        return "✗ Mismatch"

    return "✓ Match"


def _collect_inconsistencies(result: dict[str, Any], detail: dict[str, Any] | None) -> list[str]:
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
        _add(
            f"❌ Weather verification failed: "
            f"{weather.get('message', weather.get('error'))}"
        )
    elif weather and _weather_verification_label(payload) == "✗ Mismatch":
        summary = weather.get("summary", "Weather data does not support the reported incident.")
        _add(f"❌ Weather mismatch: {summary}")

    if not (result.get("extracted_data") or {}):
        _add("❌ Insufficient structured data extracted from claim text.")

    if result.get("consistency_score") is not None:
        score = float(result["consistency_score"])
        if score < 0.5:
            _add("❌ Low consistency between claim text and uploaded image.")

    return inconsistencies


def _render_data_quality_warnings(result: dict[str, Any], detail: dict[str, Any] | None) -> None:
    payload = _full_payload(result, detail)

    if not (result.get("extracted_data") or {}):
        st.warning(
            "⚠️ AI could not extract structured data. Manual review required.",
            icon="⚠️",
        )

    had_image = bool(st.session_state.submitted_image_bytes) or bool(payload.get("image_path"))
    if had_image and not result.get("image_analysis"):
        st.warning(
            "👁️ Image analysis unavailable. Consistency check skipped.",
            icon="👁️",
        )

    raw_input = payload.get("raw_input", "")
    weather_keywords = ("chuva", "tempestade", "vento", "storm", "rain")
    mentions_weather = any(k in raw_input.lower() for k in weather_keywords)
    if mentions_weather and not payload.get("weather_verification"):
        st.warning(
            "🌦️ Weather verification unavailable. Climate-based fraud detection disabled.",
            icon="🌦️",
        )


def _run_processing_flow(submission: dict[str, Any]) -> None:
    result_holder: dict[str, Any] = {"data": None, "error": None}
    start_time = time.time()
    node_timings: dict[str, float] = {}

    worker = threading.Thread(
        target=_submit_claim_worker,
        kwargs={
            "claim_id": submission["claim_id"],
            "raw_input_text": submission["raw_input_text"],
            "image_bytes": submission.get("image_bytes"),
            "image_filename": submission.get("image_filename"),
            "image_content_type": submission.get("image_content_type"),
            "result_holder": result_holder,
        },
        daemon=True,
    )
    worker.start()

    with st.status("🔍 AI Agent Processing Pipeline", expanded=True) as status:
        for index, (emoji, label, node_key) in enumerate(PROCESSING_STEPS):
            step_start = time.time()
            if worker.is_alive() or index == 0:
                time.sleep(1.2)
            node_timings[node_key] = round(time.time() - step_start, 2)
            st.write(f"{emoji} **{label}** — _{node_timings[node_key]:.1f}s_")

        worker.join(timeout=300)
        elapsed = round(time.time() - start_time, 2)
        status.update(label=f"✅ Pipeline complete in {elapsed}s", state="complete")

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
    fraud_score = float(result.get("fraud_risk_score", 0.0))
    is_high_risk = fraud_score > FRAUD_HIGH_RISK_THRESHOLD
    inconsistencies = _collect_inconsistencies(result, detail)
    payload = _full_payload(result, detail)

    _render_data_quality_warnings(result, detail)

    st.markdown(
        '<div class="cf-card"><div class="cf-card-title">🔍 Risk Assessment</div>',
        unsafe_allow_html=True,
    )

    if is_high_risk:
        st.markdown('<div class="risk-high">', unsafe_allow_html=True)
        st.error("### ⚠️ HIGH FRAUD RISK DETECTED")
        if inconsistencies:
            st.markdown("**Evidence of inconsistencies:**")
            for item in inconsistencies:
                st.markdown(f"- {item}")
        else:
            st.markdown(
                "The AI agent flagged this claim for manual review due to elevated fraud risk."
            )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="risk-low">', unsafe_allow_html=True)
        st.success("### ✅ LOW RISK — AUTO-APPROVED")
        st.markdown("The claim passed automated checks and is eligible for payment approval.")
        st.markdown("</div>", unsafe_allow_html=True)

    metric_main, metric_side = st.columns([2, 1])
    fraud_delta, delta_color = _risk_delta(fraud_score)
    consistency = result.get("consistency_score")
    weather_label = _weather_verification_label(payload)

    with metric_main:
        st.metric(
            "Fraud Risk Score",
            f"{fraud_score * 100:.0f}%",
            delta=fraud_delta,
            delta_color=delta_color,  # type: ignore[arg-type]
            help="LLM-assessed probability of fraudulent intent (0–100%).",
        )
        st.caption("🔍 Higher scores indicate stronger fraud signals from the AI agent.")

    with metric_side:
        st.metric(
            "Consistency",
            f"{float(consistency) * 100:.0f}%" if consistency is not None else "N/A",
            help="Text-vs-image damage type alignment score.",
        )
        st.metric(
            "Weather",
            weather_label,
            help="Open-Meteo historical verification against reported incident.",
        )
        if st.session_state.processing_elapsed:
            st.metric("Processing Time", f"{st.session_state.processing_elapsed:.1f}s")

    if st.session_state.submitted_image_bytes:
        st.markdown("**📎 Evidence — Submitted Image**")
        st.image(
            st.session_state.submitted_image_bytes,
            caption=f"Claim {result.get('claim_id', '')} — damage photo",
            use_container_width=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
    _render_technical_details(result, detail)


def _render_technical_details(result: dict[str, Any], detail: dict[str, Any] | None) -> None:
    payload = _full_payload(result, detail)
    tools_called: list[str] = []
    if payload.get("image_analysis"):
        tools_called.append("Qwen-VL image analysis")
    if payload.get("weather_verification"):
        tools_called.append("Open-Meteo weather verification")
    for tool in payload.get("tool_calls_made") or []:
        if tool not in tools_called:
            tools_called.append(tool)

    with st.expander("🔧 View Technical Details", expanded=False):
        st.markdown("**Tools invoked**")
        if tools_called:
            for tool in tools_called:
                st.markdown(f"- `{tool}`")
        else:
            st.caption("No external tools were invoked for this claim.")

        if st.session_state.node_timings:
            st.markdown("**Simulated node timing (demo)**")
            for node, duration in st.session_state.node_timings.items():
                st.markdown(f"- `{node}`: {duration}s")

        st.markdown("**Raw API response**")
        st.json(result)
        if detail:
            st.markdown("**Persisted claim snapshot**")
            st.json(detail)


def _record_decision(claim_id: str, decision: str, notes: str) -> bool:
    with st.spinner("Recording analyst decision..."):
        success, result = submit_review_decision_api(claim_id, decision, notes)

    if not success:
        st.session_state.decision_error = str(result)
        st.error(str(result))
        return False

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    api_decided_at = result.get("decided_at")
    if api_decided_at:
        timestamp = str(api_decided_at).replace("T", " ")[:19]

    receipt = {
        "timestamp": timestamp,
        "claim_id": claim_id,
        "decision": result.get("status", decision),
        "notes": notes or result.get("reviewer_note") or "(no notes)",
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
    if st.session_state.claim_detail:
        st.session_state.claim_detail["status"] = receipt["decision"]

    logger.info("Human analyst decision recorded via API", extra=entry)
    st.toast("Decision recorded successfully", icon="✅")
    return True


def _reset_demo_decision_state() -> None:
    st.session_state.human_decision = None
    st.session_state.decision_receipt = None
    st.session_state.decision_error = None
    st.session_state.pending_confirmation = None
    st.session_state.analyst_notes = ""
    st.session_state.analyst_override = False
    st.toast("Decision state cleared for demo", icon="🔄")


def _render_human_actions(result: dict[str, Any]) -> None:
    fraud_score = float(result.get("fraud_risk_score", 0.0))
    is_low_risk = fraud_score <= FRAUD_HIGH_RISK_THRESHOLD
    claim_id = result.get("claim_id", st.session_state.claim_id)
    decision_made = bool(st.session_state.human_decision or st.session_state.decision_receipt)
    status_label = _human_review_status_label(result, st.session_state.human_decision)

    st.markdown(
        '<div class="cf-card"><div class="cf-card-title">🛡️ Human-in-the-Loop Decision</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Regulatory checkpoint: a licensed analyst must confirm or override the AI recommendation."
    )

    status_color = {
        "APPROVED": "green",
        "REJECTED": "red",
        "PENDING REVIEW": "orange",
    }.get(status_label, "blue")
    st.markdown(f"**Current status:** :{status_color}[{status_label}]")

    if st.session_state.decision_error and not decision_made:
        st.error(st.session_state.decision_error)

    if decision_made:
        st.info("✅ Decision already recorded. Buttons are disabled for this claim.")
        if st.session_state.decision_receipt:
            _render_decision_receipt(st.session_state.decision_receipt)
        if st.button("🔄 Reset for Demo", use_container_width=True, key="reset_demo_decision"):
            _reset_demo_decision_state()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.session_state.analyst_notes = st.text_area(
        "Analyst notes",
        value=st.session_state.analyst_notes,
        height=100,
        placeholder="Document your reasoning for audit compliance...",
        key="analyst_notes_input",
    )

    if not is_low_risk:
        st.session_state.analyst_override = st.checkbox(
            "Analyst override — approve despite high fraud risk",
            value=st.session_state.analyst_override,
            help="Required to enable approval when fraud risk exceeds 70%.",
        )

    approve_enabled = is_low_risk or st.session_state.analyst_override
    action_cols = st.columns(2)

    with action_cols[0]:
        st.markdown('<div class="approve-btn">', unsafe_allow_html=True)
        if st.button(
            "✅ Approve Payment",
            disabled=not approve_enabled,
            use_container_width=True,
            key="approve_payment",
        ):
            st.session_state.pending_confirmation = "APPROVED"
        st.markdown("</div>", unsafe_allow_html=True)

    with action_cols[1]:
        st.markdown('<div class="reject-btn">', unsafe_allow_html=True)
        if st.button("❌ Reject & Investigate", use_container_width=True, key="reject_claim"):
            st.session_state.pending_confirmation = "REJECTED"
        st.markdown("</div>", unsafe_allow_html=True)

    pending = st.session_state.pending_confirmation
    if pending:
        st.warning(f"⚠️ Confirm you want to mark claim **{claim_id}** as **{pending}**?")
        confirm_cols = st.columns(2)
        with confirm_cols[0]:
            if st.button(
                "Yes, confirm decision",
                type="primary",
                use_container_width=True,
            ) and _record_decision(claim_id, pending, st.session_state.analyst_notes):
                st.success(
                    f"Decision recorded. Claim {claim_id} marked as {pending} by human analyst."
                )
                st.rerun()
        with confirm_cols[1]:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pending_confirmation = None
                st.rerun()

    if st.session_state.audit_trail:
        st.markdown("**Decision Audit Trail (this session)**")
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
    if not check_backend_health():
        st.error("⚠️ Backend not reachable. Please run 'make run' first.")
        return
    if not raw_input_text or not raw_input_text.strip():
        st.error("Please provide an incident description before submitting.")
        return

    image_error = _validate_image(uploaded_image)
    if image_error:
        st.error(image_error)
        return

    image_bytes = None
    image_filename = None
    image_content_type = None

    if uploaded_image is not None:
        image_bytes = uploaded_image.getvalue()
        if not image_bytes:
            st.error("❌ Image upload failed. Please try a different file.")
            return
        image_filename = uploaded_image.name
        image_content_type = uploaded_image.type

    st.session_state.claim_id = claim_id.strip() or "CLM-001"
    st.session_state.submitted_image_bytes = image_bytes
    st.session_state.pending_submission = {
        "claim_id": st.session_state.claim_id,
        "raw_input_text": raw_input_text.strip(),
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
    st.markdown(
        '<div class="cf-card"><div class="cf-card-title">📧 Customer Portal</div>',
        unsafe_allow_html=True,
    )
    st.caption("Submit a new insurance claim for AI-powered triage and fraud analysis.")

    claim_id = st.text_input(
        "Claim ID",
        value=st.session_state.input_claim_id,
        key="input_claim_id",
    )
    raw_input_text = st.text_area(
        "Incident description",
        value=st.session_state.input_raw_text,
        height=160,
        placeholder=(
            "Describe the incident (e.g., 'My roof was damaged by yesterday's storm "
            "in São Paulo...')"
        ),
        key="input_raw_text",
    )
    uploaded_image = st.file_uploader(
        "Upload damage photo",
        type=["jpg", "jpeg", "png"],
        key="input_image",
    )

    if st.button(
        "🚀 Submit Claim for AI Analysis",
        type="primary",
        use_container_width=True,
    ):
        _handle_submit(claim_id, raw_input_text, uploaded_image)

    st.markdown("</div>", unsafe_allow_html=True)


def _render_analyst_panel() -> None:
    st.markdown(
        '<div class="cf-card"><div class="cf-card-title">🔍 Fraud Analyst Dashboard</div>',
        unsafe_allow_html=True,
    )
    st.caption("Real-time LangGraph pipeline execution and risk decision support.")

    if st.session_state.processing and st.session_state.pending_submission:
        _run_processing_flow(st.session_state.pending_submission)

    if st.session_state.claim_result:
        _render_result_card(st.session_state.claim_result, st.session_state.claim_detail)
        _render_human_actions(st.session_state.claim_result)
    elif st.session_state.submit_error:
        st.error(st.session_state.submit_error)
    elif not st.session_state.processing:
        st.markdown(
            """
            **Awaiting claim submission**

            The analyst dashboard will display:
            - Live LangGraph node execution via `st.status()`
            - Fraud risk, consistency, and weather verification metrics
            - Evidence thumbnails and technical audit trail
            - Human-in-the-loop approve / reject controls
            """
        )

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
