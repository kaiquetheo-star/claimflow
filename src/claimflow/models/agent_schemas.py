"""Pydantic schemas enforced as structured LLM output via DashScope/Qwen."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TipoDano(StrEnum):
    """Damage category extracted during claim triage."""

    AGUA = "AGUA"
    FOGO = "FOGO"
    VENTO = "VENTO"
    OUTRO = "OUTRO"


class TriageResult(BaseModel):
    """Structured fields extracted from raw claim text by the triage LLM."""

    cliente_nome: str = Field(
        ...,
        min_length=1,
        description="Full name of the policyholder or claimant.",
    )
    tipo_dano: TipoDano = Field(
        ...,
        description="Primary type of damage reported in the claim.",
    )
    localizacao: str = Field(
        ...,
        min_length=1,
        description="Location where the incident occurred (address or city).",
    )
    descricao_resumida: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Concise summary of the incident in Portuguese.",
    )
    data_incidente: datetime | None = Field(
        default=None,
        description="Date and time of the incident, if mentioned in the text.",
    )


class RiskAssessmentResult(BaseModel):
    """Fraud and severity assessment produced by the risk LLM."""

    fraud_risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability of fraudulent intent [0.0, 1.0].",
    )
    severity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated financial/operational severity [0.0, 1.0].",
    )
    justificativa_risco: str = Field(
        ...,
        min_length=1,
        description="Evidence-based rationale for the assigned scores.",
    )
    requires_human_review: bool = Field(
        ...,
        description="Whether the claim should be escalated regardless of score thresholds.",
    )


class ToolDecision(BaseModel):
    """Structured tool-selection output from the investigation LLM (JSON mode)."""

    requires_tool_call: bool = Field(
        ...,
        description=(
            "True when the claim mentions weather/climate and external verification is needed."
        ),
    )
    tool_name: Literal["get_weather_history", "none"] = Field(
        ...,
        description="Name of the tool to invoke, or 'none' when no tool is required.",
    )
    tool_arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the selected tool (e.g. location and date).",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Brief rationale for invoking or skipping the tool.",
    )
