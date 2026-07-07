"""State definitions for the claim processing LangGraph agent."""

from typing import Any

from typing_extensions import TypedDict

from claimflow.models.enums import ClaimStatus


class ClaimAgentState(TypedDict, total=False):
    """Shared state passed between nodes in the claim processing graph.

    Attributes:
        claim_id: Unique identifier for the claim.
        raw_input: Raw text content (e.g. email body) submitted for processing.
        image_path: Local filesystem path to an uploaded claim photo, if any.
        extracted_data: Structured triage fields serialised as a plain dict.
        image_analysis: Qwen-VL visual analysis result serialised as a plain dict.
        consistency_score: Text-vs-image damage consistency in [0.0, 1.0].
        fraud_risk_score: LLM-assessed fraud probability [0.0, 1.0].
        severity_score: LLM-assessed incident severity [0.0, 1.0].
        risk_assessment: Full risk assessment payload serialised as a plain dict.
        risk_score: Composite score (max of fraud and severity) for API consumers.
        requires_human_review: Flag set by the risk LLM for manual escalation.
        weather_verification: Result from ``get_weather_history`` when climate is investigated.
        tool_calls_made: Names of tools invoked during investigation.
        system_error: True when all LLM/vision models failed and the claim needs ops review.
        status: Current processing status of the claim.
        error: Error message when triage or risk assessment fails.
        error_message: Structured error detail for API consumers (mirrors ``error`` on failure).
    """

    claim_id: str
    raw_input: str
    image_path: str | None
    extracted_data: dict[str, Any]
    image_analysis: dict[str, Any] | None
    consistency_score: float | None
    fraud_risk_score: float
    severity_score: float
    risk_assessment: dict[str, Any]
    risk_score: float
    requires_human_review: bool
    weather_verification: dict[str, Any] | None
    tool_calls_made: list[str]
    system_error: bool
    status: ClaimStatus
    error: str
    error_message: str
