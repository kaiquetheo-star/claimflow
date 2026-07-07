"""Pydantic models for API request and response contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from claimflow.agents.states import ClaimStatus


class ImageAnalysisResult(BaseModel):
    """Structured visual analysis returned by Qwen-VL."""

    detected_damage_type: str = Field(
        ...,
        description="Damage category detected in the image (AGUA, FOGO, VENTO, OUTRO).",
    )
    visual_severity: str = Field(
        ...,
        description="Visual severity assessment (baixa, media, alta, critica).",
    )
    location_match: bool = Field(
        ...,
        description="Whether the image location context matches the textual report.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Detailed visual description of the damage in Portuguese.",
    )
    inconsistencies: list[str] = Field(
        default_factory=list,
        description="List of text-vs-image inconsistencies identified by the model.",
    )


class ClaimSubmissionRequest(BaseModel):
    """Validated fields for multipart claim submission (form fields)."""

    claim_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique identifier for the claim (e.g. external reference number).",
        examples=["CLM-2026-00042"],
    )
    raw_input_text: str = Field(
        ...,
        min_length=1,
        description="Raw text content of the claim submission (e.g. email body).",
        examples=[
            "Assunto: Sinistro residencial\n\n"
            "Boa tarde, sou Maria Silva. Houve um vazamento de água no meu apartamento "
            "em São Paulo no dia 15/03/2026, causando danos no piso e na parede."
        ],
    )

    @field_validator("claim_id", "raw_input_text", mode="before")
    @classmethod
    def strip_whitespace(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


class ClaimResponse(BaseModel):
    """Result returned after the claim has been processed by the agent pipeline."""

    claim_id: str = Field(..., description="Unique identifier for the claim.")
    status: ClaimStatus = Field(..., description="Final processing status.")
    extracted_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured triage fields extracted from the raw input.",
    )
    image_analysis: dict[str, Any] | None = Field(
        default=None,
        description="Qwen-VL visual analysis result, if an image was provided.",
    )
    consistency_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Text-vs-image damage consistency score [0.0, 1.0].",
    )
    fraud_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM-assessed fraud probability [0.0, 1.0].",
    )
    severity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM-assessed incident severity [0.0, 1.0].",
    )
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Composite risk score (max of fraud and severity).",
    )
    risk_assessment: dict[str, Any] = Field(
        default_factory=dict,
        description="Full risk assessment payload from the LLM.",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Whether manual review was flagged by the risk LLM.",
    )
    error: str | None = Field(
        default=None,
        description="Error message when a pipeline node fails gracefully.",
    )


class ReviewQueueItem(BaseModel):
    """Summary row for the human-review dashboard queue."""

    claim_id: str
    status: ClaimStatus
    fraud_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float | None = Field(default=None, ge=0.0, le=1.0)
    cliente_nome: str | None = None
    tipo_dano: str | None = None
    updated_at: datetime | None = None


class ReviewQueueResponse(BaseModel):
    """Paginated list of claims awaiting human review."""

    items: list[ReviewQueueItem]
    total: int
    limit: int
    offset: int


class ReviewDetailResponse(BaseModel):
    """Full claim snapshot for adjuster review."""

    claim_id: str
    status: ClaimStatus
    payload: dict[str, Any]
    reviewer_note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReviewDecisionRequest(BaseModel):
    """Adjuster decision on a queued claim."""

    decision: Literal["APPROVED", "REJECTED"]
    reviewer_note: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional note explaining the adjuster's decision.",
    )


class ReviewDecisionResponse(BaseModel):
    """Confirmation of an adjuster decision."""

    claim_id: str
    status: ClaimStatus
    reviewer_note: str | None = None
