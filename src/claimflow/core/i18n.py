"""Lightweight i18n module for Claimflow.

Supports: en (default), pt, es
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal

Language = Literal["en", "pt", "es"]

DEFAULT_LANGUAGE: Language = "en"

_request_language_var: ContextVar[Language] = ContextVar("request_language", default=DEFAULT_LANGUAGE)

LANGUAGE_DISPLAY_NAMES: dict[Language, str] = {
    "en": "English",
    "pt": "Portuguese",
    "es": "Spanish",
}

TRANSLATIONS: dict[Language, dict[str, str]] = {
    "en": {
        # UI - Header
        "app_title": "🛡️ Claimflow: AI-Powered Insurance Claims Autopilot",
        "app_subtitle": "Powered by Qwen Cloud | Track 4: Autopilot Agent",
        # UI - Customer Portal
        "customer_portal_title": "📧 Submit Insurance Claim",
        "claim_id_label": "Claim ID",
        "claim_text_label": "Describe the incident",
        "claim_text_placeholder": (
            "E.g., 'My roof was damaged by yesterday's storm in São Paulo...'"
        ),
        "upload_label": "Upload evidence photo",
        "submit_button": "🚀 Submit Claim for AI Analysis",
        # UI - Analyst Dashboard
        "analyst_dashboard_title": "🔍 AI Agent Processing",
        "receiving_data": "✓ Receiving claim data...",
        "extracting_text": "🤖 Extracting structured data from text...",
        "analyzing_image": "👁️ Analyzing image with Qwen-VL...",
        "verifying_weather": "🌦️ Verifying weather conditions via Open-Meteo...",
        "calculating_risk": "⚖️ Calculating fraud risk score...",
        "processing_complete": "Processing complete",
        # UI - Risk Results
        "high_risk_title": "⚠️ HIGH FRAUD RISK DETECTED",
        "high_risk_desc": "Evidence of inconsistencies:",
        "low_risk_title": "✅ LOW RISK — AUTO-APPROVED",
        "low_risk_desc": (
            "The claim passed automated checks and is eligible for payment approval."
        ),
        "fraud_risk_score": "Fraud Risk Score",
        "consistency_score": "Consistency Score",
        "weather_verification": "Weather Verification",
        "processing_time": "Processing Time",
        "higher_scores_note": (
            "Higher scores indicate stronger fraud signals from the AI agent."
        ),
        # UI - HITL
        "hitl_title": "Human-in-the-Loop Decision",
        "hitl_description": (
            "Track 4 requires a human analyst checkpoint before funds are released."
        ),
        "analyst_notes_label": "Analyst Notes",
        "approve_button": "✅ Approve Payment",
        "reject_button": "❌ Reject & Investigate",
        "decision_recorded": "Decision recorded: {}",
        "decision_receipt": "Decision Receipt",
        # UI - Sidebar
        "language_selector": "🌐 Language",
        "demo_mode_label": "Demo Mode",
        "demo_mode_help": "Load pre-configured example claims",
        "system_status": "System Status",
        "todays_claims": "Today's Claims",
        "fraud_detection_rate": "Fraud Detection Rate",
        "current_scenario": "📊 Current Scenario",
        # UI - Warnings
        "insufficient_data": (
            "⚠️ AI could not extract structured data. Manual review required."
        ),
        "image_unavailable": (
            "👁️ Image analysis unavailable. Consistency check skipped."
        ),
        "weather_unavailable": (
            "🌦️ Weather verification unavailable. "
            "Climate-based fraud detection disabled."
        ),
        "demo_mode_active": "🎭 Demo Mode Active",
        "demo_mode_desc": (
            "The system is using deterministic MockLLM scenarios "
            "for consistent demonstration."
        ),
        # UI - Examples
        "example_storm": "🌪️ Example 1: Legitimate Storm Claim",
        "example_fraud": "🔥 Example 2: Obvious Fraud",
        "example_ambiguous": "❓ Example 3: Ambiguous Case",
        "reset_demo": "🔄 Reset for Next Demo",
        # UI - Errors
        "backend_unreachable": (
            "⚠️ Backend not reachable. Please run 'make run' first."
        ),
        "upload_failed": "❌ Image upload failed. Please try a different file.",
        "api_error": "❌ API error: {}",
        # Evidence / Reasons
        "reason_empty_extraction": (
            "❌ Insufficient structured data extracted from claim text."
        ),
        "reason_image_mismatch": "❌ Image shows {} but text claims {}.",
        "reason_weather_mismatch": (
            "❌ Weather data contradicts claim (reported: {}, actual: {})."
        ),
        "reason_missing_image": "⚠️ No image provided for visual verification.",
        "reason_missing_weather": "⚠️ Weather verification unavailable.",
        # Extended — Sidebar & status
        "control_panel": "🛡️ Control Panel",
        "operational": "Operational",
        "offline": "Offline",
        "backend_caption": "Live connection to FastAPI backend on port 8000.",
        "claims_caption": "Claims processed across all channels today.",
        "fraud_rate_caption": "Share of submissions flagged for human review.",
        "quick_load_examples": "Quick-load examples",
        "decision_history": "📋 Decision History",
        "no_decisions_yet": "No analyst decisions recorded yet.",
        "no_notes": "(no notes)",
        # Extended — Panels
        "customer_portal_caption": (
            "Submit a new insurance claim for AI-powered triage and fraud analysis."
        ),
        "analyst_panel_title": "🔍 Fraud Analyst Dashboard",
        "analyst_panel_caption": (
            "Real-time LangGraph pipeline execution and risk decision support."
        ),
        "awaiting_submission": "Awaiting claim submission",
        "awaiting_submission_details": (
            "The analyst dashboard will display:\n"
            "- Live LangGraph node execution via `st.status()`\n"
            "- Fraud risk, consistency, and weather verification metrics\n"
            "- Evidence thumbnails and technical audit trail\n"
            "- Human-in-the-loop approve / reject controls"
        ),
        "pipeline_status": "🔍 AI Agent Processing Pipeline",
        "pipeline_complete": "✅ Pipeline complete in {}s",
        "risk_assessment_title": "🔍 Risk Assessment",
        "flagged_for_review": (
            "The AI agent flagged this claim for manual review "
            "due to elevated fraud risk."
        ),
        "evidence_image": "📎 Evidence — Submitted Image",
        "damage_photo_caption": "Claim {} — damage photo",
        "technical_details": "🔧 View Technical Details",
        "tools_invoked": "Tools invoked",
        "no_tools": "No external tools were invoked for this claim.",
        "node_timing": "Simulated node timing (demo)",
        "raw_api_response": "Raw API response",
        "persisted_snapshot": "Persisted claim snapshot",
        # Extended — Decisions
        "recording_decision": "Recording analyst decision...",
        "decision_toast": "Decision recorded successfully",
        "reset_toast": "Decision state cleared for demo",
        "hitl_caption": (
            "Regulatory checkpoint: a licensed analyst must confirm or override "
            "the AI recommendation."
        ),
        "current_status": "Current status:",
        "waiting_human": (
            "⏳ **Waiting for human decision…**\n\n"
            "LangGraph is **paused** at `interrupt_before=['human_review']`. "
            "Submitting Approve/Reject calls `update_state` + resume on the API."
        ),
        "decision_already_recorded": (
            "✅ Decision already recorded. LangGraph resumed and buttons are disabled."
        ),
        "auto_finished_caption": (
            "This claim finished automatically (approval/rejection). "
            "HITL controls appear when the graph pauses for review."
        ),
        "analyst_notes_placeholder": "Document your reasoning for audit compliance...",
        "analyst_override": "Analyst override — approve despite high fraud risk",
        "analyst_override_help": (
            "Required to enable approval when fraud risk exceeds 70%."
        ),
        "confirm_decision": (
            "⚠️ Confirm you want to mark claim **{}** as **{}**?"
        ),
        "yes_confirm": "Yes, confirm decision",
        "cancel": "Cancel",
        "decision_success": (
            "Decision recorded. Claim {} marked as {} by human analyst."
        ),
        "audit_trail": "Decision Audit Trail (this session)",
        # Extended — Errors & validation
        "empty_description_error": (
            "Please provide an incident description before submitting."
        ),
        "upload_type_error": (
            "❌ Image upload failed. Please try a different file "
            "(jpg, jpeg, or png only)."
        ),
        "timeout_error": (
            "Request timed out while processing the claim. Please try again."
        ),
        "network_error": "Network error: {}",
        "claim_not_found": (
            "Claim not found. Submit the claim before recording a decision."
        ),
        "decision_already_api": "Decision already recorded for this claim.",
        # Extended — Verification labels
        "match": "✓ Match",
        "mismatch": "✗ Mismatch",
        "not_checked": "— Not checked",
        "weather_failed": "❌ Weather verification failed: {}",
        "weather_mismatch": "❌ Weather mismatch: {}",
        "low_consistency": (
            "❌ Low consistency between claim text and uploaded image."
        ),
        # Extended — Demo / health
        "qwen_connected": (
            "Real Qwen Cloud connectivity verified via /health endpoint (200 OK)."
        ),
        "qwen_pending": (
            "DashScope health check pending — verify DASHSCOPE_API_KEY in .env."
        ),
        "scenario_why": "Why: {}",
        "scenario_expected": "Expected: {}",
        "receipt_claim": "Claim:",
        "receipt_decision": "Decision:",
        "receipt_analyst": "Analyst:",
        "receipt_recorded": "Recorded at:",
        "receipt_notes": "Notes:",
        "demo_hint_fraud": (
            "Upload a water-damage / leak photo to trigger text-vs-image inconsistency."
        ),
        "demo_hint_legit": (
            "Upload a storm / water damage photo for a consistent claim."
        ),
        "demo_hint_ambiguous": (
            "Submit without an image to test fail-closed data extraction handling."
        ),
    },
    "pt": {
        # UI - Header
        "app_title": "🛡️ Claimflow: Autopilot de Sinistros com IA",
        "app_subtitle": "Powered by Qwen Cloud | Track 4: Autopilot Agent",
        # UI - Customer Portal
        "customer_portal_title": "📧 Submeter Sinistro",
        "claim_id_label": "ID do Sinistro",
        "claim_text_label": "Descreva o incidente",
        "claim_text_placeholder": (
            "Ex: 'Meu telhado foi danificado pela tempestade de ontem em São Paulo...'"
        ),
        "upload_label": "Upload da foto de evidência",
        "submit_button": "🚀 Submeter para Análise de IA",
        # UI - Analyst Dashboard
        "analyst_dashboard_title": "🔍 Processamento do Agente IA",
        "receiving_data": "✓ Recebendo dados do sinistro...",
        "extracting_text": "🤖 Extraindo dados estruturados do texto...",
        "analyzing_image": "👁️ Analisando imagem com Qwen-VL...",
        "verifying_weather": "🌦️ Verificando condições climáticas via Open-Meteo...",
        "calculating_risk": "⚖️ Calculando score de risco de fraude...",
        "processing_complete": "Processamento completo",
        # UI - Risk Results
        "high_risk_title": "⚠️ ALTO RISCO DE FRAUDE DETECTADO",
        "high_risk_desc": "Evidências de inconsistências:",
        "low_risk_title": "✅ BAIXO RISCO — AUTO-APROVADO",
        "low_risk_desc": (
            "O sinistro passou nas verificações automáticas e está elegível para pagamento."
        ),
        "fraud_risk_score": "Score de Risco de Fraude",
        "consistency_score": "Score de Consistência",
        "weather_verification": "Verificação Climática",
        "processing_time": "Tempo de Processamento",
        "higher_scores_note": "Scores maiores indicam sinais mais fortes de fraude.",
        # UI - HITL
        "hitl_title": "Decisão Humana no Loop",
        "hitl_description": (
            "Track 4 exige checkpoint humano antes da liberação de fundos."
        ),
        "analyst_notes_label": "Notas do Analista",
        "approve_button": "✅ Aprovar Pagamento",
        "reject_button": "❌ Rejeitar e Investigar",
        "decision_recorded": "Decisão registrada: {}",
        "decision_receipt": "Recibo da Decisão",
        # UI - Sidebar
        "language_selector": "🌐 Idioma",
        "demo_mode_label": "Modo Demo",
        "demo_mode_help": "Carregar sinistros de exemplo pré-configurados",
        "system_status": "Status do Sistema",
        "todays_claims": "Sinistros Hoje",
        "fraud_detection_rate": "Taxa de Detecção de Fraude",
        "current_scenario": "📊 Cenário Atual",
        # UI - Warnings
        "insufficient_data": (
            "⚠️ IA não conseguiu extrair dados estruturados. Revisão manual necessária."
        ),
        "image_unavailable": (
            "👁️ Análise de imagem indisponível. Verificação de consistência ignorada."
        ),
        "weather_unavailable": "🌦️ Verificação climática indisponível.",
        "demo_mode_active": "🎭 Modo Demo Ativo",
        "demo_mode_desc": (
            "O sistema usa cenários MockLLM determinísticos para demonstração consistente."
        ),
        # UI - Examples
        "example_storm": "🌪️ Exemplo 1: Sinistro Legítimo de Tempestade",
        "example_fraud": "🔥 Exemplo 2: Fraude Óbvia",
        "example_ambiguous": "❓ Exemplo 3: Caso Ambíguo",
        "reset_demo": "🔄 Resetar para Próxima Demo",
        # UI - Errors
        "backend_unreachable": "⚠️ Backend inacessível. Execute 'make run' primeiro.",
        "upload_failed": "❌ Upload de imagem falhou. Tente outro arquivo.",
        "api_error": "❌ Erro da API: {}",
        # Evidence / Reasons
        "reason_empty_extraction": (
            "❌ Dados estruturados insuficientes extraídos do texto."
        ),
        "reason_image_mismatch": "❌ Imagem mostra {} mas texto alega {}.",
        "reason_weather_mismatch": (
            "❌ Dados climáticos contradizem sinistro (relatado: {}, real: {})."
        ),
        "reason_missing_image": "⚠️ Nenhuma imagem fornecida para verificação visual.",
        "reason_missing_weather": "⚠️ Verificação climática indisponível.",
        # Extended — Sidebar & status
        "control_panel": "🛡️ Painel de Controle",
        "operational": "Operacional",
        "offline": "Offline",
        "backend_caption": "Conexão ativa com o backend FastAPI na porta 8000.",
        "claims_caption": "Sinistros processados em todos os canais hoje.",
        "fraud_rate_caption": (
            "Percentual de submissões sinalizadas para revisão humana."
        ),
        "quick_load_examples": "Exemplos rápidos",
        "decision_history": "📋 Histórico de Decisões",
        "no_decisions_yet": "Nenhuma decisão de analista registrada ainda.",
        "no_notes": "(sem notas)",
        # Extended — Panels
        "customer_portal_caption": (
            "Submeta um novo sinistro para triagem com IA e análise de fraude."
        ),
        "analyst_panel_title": "🔍 Painel do Analista de Fraude",
        "analyst_panel_caption": (
            "Execução do pipeline LangGraph em tempo real e suporte à decisão de risco."
        ),
        "awaiting_submission": "Aguardando submissão de sinistro",
        "awaiting_submission_details": (
            "O painel do analista exibirá:\n"
            "- Execução dos nós LangGraph ao vivo via `st.status()`\n"
            "- Métricas de risco de fraude, consistência e verificação climática\n"
            "- Miniaturas de evidências e trilha de auditoria técnica\n"
            "- Controles human-in-the-loop de aprovar / rejeitar"
        ),
        "pipeline_status": "🔍 Pipeline de Processamento do Agente IA",
        "pipeline_complete": "✅ Pipeline concluído em {}s",
        "risk_assessment_title": "🔍 Avaliação de Risco",
        "flagged_for_review": (
            "O agente IA sinalizou este sinistro para revisão manual "
            "devido ao risco elevado de fraude."
        ),
        "evidence_image": "📎 Evidência — Imagem Enviada",
        "damage_photo_caption": "Sinistro {} — foto do dano",
        "technical_details": "🔧 Ver Detalhes Técnicos",
        "tools_invoked": "Ferramentas invocadas",
        "no_tools": "Nenhuma ferramenta externa foi invocada para este sinistro.",
        "node_timing": "Tempo simulado por nó (demo)",
        "raw_api_response": "Resposta bruta da API",
        "persisted_snapshot": "Snapshot persistido do sinistro",
        # Extended — Decisions
        "recording_decision": "Registrando decisão do analista...",
        "decision_toast": "Decisão registrada com sucesso",
        "reset_toast": "Estado da decisão limpo para demo",
        "hitl_caption": (
            "Checkpoint regulatório: um analista licenciado deve confirmar ou "
            "sobrescrever a recomendação da IA."
        ),
        "current_status": "Status atual:",
        "waiting_human": (
            "⏳ **Aguardando decisão humana…**\n\n"
            "O LangGraph está **pausado** em `interrupt_before=['human_review']`. "
            "Aprovar/Rejeitar chama `update_state` + retomada na API."
        ),
        "decision_already_recorded": (
            "✅ Decisão já registrada. LangGraph retomado e botões desabilitados."
        ),
        "auto_finished_caption": (
            "Este sinistro foi finalizado automaticamente (aprovação/rejeição). "
            "Controles HITL aparecem quando o grafo pausa para revisão."
        ),
        "analyst_notes_placeholder": (
            "Documente seu raciocínio para conformidade de auditoria..."
        ),
        "analyst_override": (
            "Sobrescrita do analista — aprovar apesar do alto risco de fraude"
        ),
        "analyst_override_help": (
            "Necessário para habilitar aprovação quando o risco de fraude excede 70%."
        ),
        "confirm_decision": (
            "⚠️ Confirma marcar o sinistro **{}** como **{}**?"
        ),
        "yes_confirm": "Sim, confirmar decisão",
        "cancel": "Cancelar",
        "decision_success": (
            "Decisão registrada. Sinistro {} marcado como {} pelo analista humano."
        ),
        "audit_trail": "Trilha de Auditoria de Decisões (esta sessão)",
        # Extended — Errors & validation
        "empty_description_error": (
            "Forneça uma descrição do incidente antes de submeter."
        ),
        "upload_type_error": (
            "❌ Upload de imagem falhou. Tente outro arquivo (apenas jpg, jpeg ou png)."
        ),
        "timeout_error": (
            "A requisição expirou ao processar o sinistro. Tente novamente."
        ),
        "network_error": "Erro de rede: {}",
        "claim_not_found": (
            "Sinistro não encontrado. Submeta o sinistro antes de registrar uma decisão."
        ),
        "decision_already_api": "Decisão já registrada para este sinistro.",
        # Extended — Verification labels
        "match": "✓ Compatível",
        "mismatch": "✗ Incompatível",
        "not_checked": "— Não verificado",
        "weather_failed": "❌ Verificação climática falhou: {}",
        "weather_mismatch": "❌ Incompatibilidade climática: {}",
        "low_consistency": (
            "❌ Baixa consistência entre o texto do sinistro e a imagem enviada."
        ),
        # Extended — Demo / health
        "qwen_connected": (
            "Conectividade real com Qwen Cloud verificada via endpoint /health (200 OK)."
        ),
        "qwen_pending": (
            "Verificação de saúde do DashScope pendente — confira DASHSCOPE_API_KEY no .env."
        ),
        "scenario_why": "Por quê: {}",
        "scenario_expected": "Esperado: {}",
        "receipt_claim": "Sinistro:",
        "receipt_decision": "Decisão:",
        "receipt_analyst": "Analista:",
        "receipt_recorded": "Registrado em:",
        "receipt_notes": "Notas:",
        "demo_hint_fraud": (
            "Envie uma foto de vazamento/dano por água para disparar inconsistência texto vs imagem."
        ),
        "demo_hint_legit": (
            "Envie uma foto de tempestade/dano por água para um sinistro consistente."
        ),
        "demo_hint_ambiguous": (
            "Submeta sem imagem para testar o tratamento fail-closed de extração de dados."
        ),
    },
    "es": {
        # UI - Header
        "app_title": "🛡️ Claimflow: Autopiloto de Siniestros con IA",
        "app_subtitle": "Powered by Qwen Cloud | Track 4: Autopilot Agent",
        # UI - Customer Portal
        "customer_portal_title": "📧 Enviar Siniestro",
        "claim_id_label": "ID del Siniestro",
        "claim_text_label": "Describa el incidente",
        "claim_text_placeholder": (
            "Ej: 'Mi techo fue dañado por la tormenta de ayer en São Paulo...'"
        ),
        "upload_label": "Subir foto de evidencia",
        "submit_button": "🚀 Enviar para Análisis de IA",
        # UI - Analyst Dashboard
        "analyst_dashboard_title": "🔍 Procesamiento del Agente IA",
        "receiving_data": "✓ Recibiendo datos del siniestro...",
        "extracting_text": "🤖 Extrayendo datos estructurados del texto...",
        "analyzing_image": "👁️ Analizando imagen con Qwen-VL...",
        "verifying_weather": "🌦️ Verificando condiciones climáticas vía Open-Meteo...",
        "calculating_risk": "⚖️ Calculando puntaje de riesgo de fraude...",
        "processing_complete": "Procesamiento completo",
        # UI - Risk Results
        "high_risk_title": "⚠️ ALTO RIESGO DE FRAUDE DETECTADO",
        "high_risk_desc": "Evidencias de inconsistencias:",
        "low_risk_title": "✅ BAJO RIESGO — AUTO-APROBADO",
        "low_risk_desc": (
            "El siniestro pasó las verificaciones automáticas y es elegible para pago."
        ),
        "fraud_risk_score": "Puntaje de Riesgo de Fraude",
        "consistency_score": "Puntaje de Consistencia",
        "weather_verification": "Verificación Climática",
        "processing_time": "Tiempo de Procesamiento",
        "higher_scores_note": (
            "Puntajes más altos indican señales más fuertes de fraude."
        ),
        # UI - HITL
        "hitl_title": "Decisión Humana en el Loop",
        "hitl_description": (
            "Track 4 requiere checkpoint humano antes de liberar fondos."
        ),
        "analyst_notes_label": "Notas del Analista",
        "approve_button": "✅ Aprobar Pago",
        "reject_button": "❌ Rechazar e Investigar",
        "decision_recorded": "Decisión registrada: {}",
        "decision_receipt": "Recibo de Decisión",
        # UI - Sidebar
        "language_selector": "🌐 Idioma",
        "demo_mode_label": "Modo Demo",
        "demo_mode_help": "Cargar siniestros de ejemplo preconfigurados",
        "system_status": "Estado del Sistema",
        "todays_claims": "Siniestros Hoy",
        "fraud_detection_rate": "Tasa de Detección de Fraude",
        "current_scenario": "📊 Escenario Actual",
        # UI - Warnings
        "insufficient_data": (
            "⚠️ IA no pudo extraer datos estructurados. Revisión manual requerida."
        ),
        "image_unavailable": "👁️ Análisis de imagen no disponible.",
        "weather_unavailable": "🌦️ Verificación climática no disponible.",
        "demo_mode_active": "🎭 Modo Demo Activo",
        "demo_mode_desc": (
            "El sistema usa escenarios MockLLM determinísticos para demostración consistente."
        ),
        # UI - Examples
        "example_storm": "🌪️ Ejemplo 1: Siniestro Legítimo de Tormenta",
        "example_fraud": "🔥 Ejemplo 2: Fraude Obvio",
        "example_ambiguous": "❓ Ejemplo 3: Caso Ambiguo",
        "reset_demo": "🔄 Reiniciar para Próxima Demo",
        # UI - Errors
        "backend_unreachable": (
            "⚠️ Backend inaccesible. Ejecute 'make run' primero."
        ),
        "upload_failed": "❌ Error al subir imagen. Intente otro archivo.",
        "api_error": "❌ Error de API: {}",
        # Evidence / Reasons
        "reason_empty_extraction": (
            "❌ Datos estructurados insuficientes extraídos del texto."
        ),
        "reason_image_mismatch": "❌ Imagen muestra {} pero texto reclama {}.",
        "reason_weather_mismatch": (
            "❌ Datos climáticos contradicen siniestro (reportado: {}, real: {})."
        ),
        "reason_missing_image": (
            "⚠️ No se proporcionó imagen para verificación visual."
        ),
        "reason_missing_weather": "⚠️ Verificación climática no disponible.",
        # Extended — Sidebar & status
        "control_panel": "🛡️ Panel de Control",
        "operational": "Operativo",
        "offline": "Desconectado",
        "backend_caption": "Conexión activa con el backend FastAPI en el puerto 8000.",
        "claims_caption": "Siniestros procesados en todos los canales hoy.",
        "fraud_rate_caption": (
            "Porcentaje de envíos marcados para revisión humana."
        ),
        "quick_load_examples": "Ejemplos rápidos",
        "decision_history": "📋 Historial de Decisiones",
        "no_decisions_yet": "Aún no hay decisiones de analista registradas.",
        "no_notes": "(sin notas)",
        # Extended — Panels
        "customer_portal_caption": (
            "Envíe un nuevo siniestro para triaje con IA y análisis de fraude."
        ),
        "analyst_panel_title": "🔍 Panel del Analista de Fraude",
        "analyst_panel_caption": (
            "Ejecución del pipeline LangGraph en tiempo real y soporte de decisión de riesgo."
        ),
        "awaiting_submission": "Esperando envío de siniestro",
        "awaiting_submission_details": (
            "El panel del analista mostrará:\n"
            "- Ejecución en vivo de nodos LangGraph vía `st.status()`\n"
            "- Métricas de riesgo de fraude, consistencia y verificación climática\n"
            "- Miniaturas de evidencia y trazabilidad técnica de auditoría\n"
            "- Controles human-in-the-loop de aprobar / rechazar"
        ),
        "pipeline_status": "🔍 Pipeline de Procesamiento del Agente IA",
        "pipeline_complete": "✅ Pipeline completado en {}s",
        "risk_assessment_title": "🔍 Evaluación de Riesgo",
        "flagged_for_review": (
            "El agente IA marcó este siniestro para revisión manual "
            "debido al riesgo elevado de fraude."
        ),
        "evidence_image": "📎 Evidencia — Imagen Enviada",
        "damage_photo_caption": "Siniestro {} — foto del daño",
        "technical_details": "🔧 Ver Detalles Técnicos",
        "tools_invoked": "Herramientas invocadas",
        "no_tools": "No se invocaron herramientas externas para este siniestro.",
        "node_timing": "Tiempo simulado por nodo (demo)",
        "raw_api_response": "Respuesta bruta de la API",
        "persisted_snapshot": "Instantánea persistida del siniestro",
        # Extended — Decisions
        "recording_decision": "Registrando decisión del analista...",
        "decision_toast": "Decisión registrada con éxito",
        "reset_toast": "Estado de decisión limpiado para demo",
        "hitl_caption": (
            "Checkpoint regulatorio: un analista licenciado debe confirmar o "
            "anular la recomendación de la IA."
        ),
        "current_status": "Estado actual:",
        "waiting_human": (
            "⏳ **Esperando decisión humana…**\n\n"
            "LangGraph está **pausado** en `interrupt_before=['human_review']`. "
            "Aprobar/Rechazar llama a `update_state` + reanudación en la API."
        ),
        "decision_already_recorded": (
            "✅ Decisión ya registrada. LangGraph reanudado y botones deshabilitados."
        ),
        "auto_finished_caption": (
            "Este siniestro finalizó automáticamente (aprobación/rechazo). "
            "Los controles HITL aparecen cuando el grafo pausa para revisión."
        ),
        "analyst_notes_placeholder": (
            "Documente su razonamiento para cumplimiento de auditoría..."
        ),
        "analyst_override": (
            "Anulación del analista — aprobar a pesar del alto riesgo de fraude"
        ),
        "analyst_override_help": (
            "Requerido para habilitar aprobación cuando el riesgo de fraude supera el 70%."
        ),
        "confirm_decision": (
            "⚠️ ¿Confirma marcar el siniestro **{}** como **{}**?"
        ),
        "yes_confirm": "Sí, confirmar decisión",
        "cancel": "Cancelar",
        "decision_success": (
            "Decisión registrada. Siniestro {} marcado como {} por analista humano."
        ),
        "audit_trail": "Trazabilidad de Decisiones (esta sesión)",
        # Extended — Errors & validation
        "empty_description_error": (
            "Proporcione una descripción del incidente antes de enviar."
        ),
        "upload_type_error": (
            "❌ Error al subir imagen. Intente otro archivo (solo jpg, jpeg o png)."
        ),
        "timeout_error": (
            "La solicitud expiró al procesar el siniestro. Intente de nuevo."
        ),
        "network_error": "Error de red: {}",
        "claim_not_found": (
            "Siniestro no encontrado. Envíe el siniestro antes de registrar una decisión."
        ),
        "decision_already_api": "Decisión ya registrada para este siniestro.",
        # Extended — Verification labels
        "match": "✓ Coincide",
        "mismatch": "✗ No coincide",
        "not_checked": "— No verificado",
        "weather_failed": "❌ Verificación climática falló: {}",
        "weather_mismatch": "❌ Incompatibilidad climática: {}",
        "low_consistency": (
            "❌ Baja consistencia entre el texto del siniestro y la imagen enviada."
        ),
        # Extended — Demo / health
        "qwen_connected": (
            "Conectividad real con Qwen Cloud verificada vía endpoint /health (200 OK)."
        ),
        "qwen_pending": (
            "Verificación de salud de DashScope pendiente — verifique DASHSCOPE_API_KEY en .env."
        ),
        "scenario_why": "Por qué: {}",
        "scenario_expected": "Esperado: {}",
        "receipt_claim": "Siniestro:",
        "receipt_decision": "Decisión:",
        "receipt_analyst": "Analista:",
        "receipt_recorded": "Registrado en:",
        "receipt_notes": "Notas:",
        "demo_hint_fraud": (
            "Suba una foto de daño por agua/filtración para disparar inconsistencia texto vs imagen."
        ),
        "demo_hint_legit": (
            "Suba una foto de tormenta/daño por agua para un siniestro consistente."
        ),
        "demo_hint_ambiguous": (
            "Envíe sin imagen para probar el manejo fail-closed de extracción de datos."
        ),
    },
}


def normalize_language(value: str | None) -> Language:
    """Normalize a BCP-47 tag or language code to a supported Language."""
    if not value:
        return DEFAULT_LANGUAGE

    code = value.strip().lower().replace("_", "-").split("-", maxsplit=1)[0]
    if code in TRANSLATIONS:
        return code  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


def t(key: str, lang: Language = "en", *args: object) -> str:
    """Get translated string for the given key and language."""
    catalog = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANGUAGE])
    text = catalog.get(key, TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))
    if args:
        return text.format(*args)
    return text


def get_available_languages() -> list[tuple[str, str]]:
    """Return list of (code, display_name) tuples for the language selector."""
    return [
        ("en", "🇺🇸 English"),
        ("pt", "🇧🇷 Português"),
        ("es", "🇪🇸 Español"),
    ]


def llm_output_instruction(lang: Language) -> str:
    """Return an English system instruction for LLM free-text output language."""
    normalized = normalize_language(lang)
    display_name = LANGUAGE_DISPLAY_NAMES[normalized]
    return (
        f"Write all free-text fields, explanations, and user-facing narrative in "
        f"{display_name}. Keep enum values, status codes, damage-type codes, and "
        f"technical identifiers unchanged (e.g. APPROVED, REJECTED, AGUA, VENTO, FOGO, "
        f"HUMAN_REVIEW)."
    )


def set_request_language(lang: Language | str | None) -> Language:
    """Set the request-scoped language (e.g. per FastAPI request or Streamlit rerun)."""
    normalized = normalize_language(lang)
    _request_language_var.set(normalized)
    return normalized


def get_request_language() -> Language:
    """Return the current request-scoped language, defaulting to English."""
    return _request_language_var.get()
