"""Shared enums used across API models and agent state — no agent/graph imports."""

from enum import StrEnum


class ClaimStatus(StrEnum):
    """Lifecycle status of a claim within the agent pipeline."""

    PENDING = "PENDING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
