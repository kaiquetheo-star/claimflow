"""Human-review dashboard API for adjuster workflows."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from claimflow.agents.states import ClaimStatus
from claimflow.api.dependencies import get_claim_store
from claimflow.core.logging import get_logger
from claimflow.models.schemas import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewDetailResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
)
from claimflow.services.claim_store import ClaimStore

router = APIRouter(prefix="/review", tags=["human-review"])
logger = get_logger(__name__)


def _queue_item_from_snapshot(snapshot) -> ReviewQueueItem:
    payload = snapshot.payload
    extracted = payload.get("extracted_data") or {}
    return ReviewQueueItem(
        claim_id=snapshot.claim_id,
        status=snapshot.status,
        fraud_risk_score=float(payload.get("fraud_risk_score", 0.0)),
        severity_score=float(payload.get("severity_score", 0.0)),
        consistency_score=payload.get("consistency_score"),
        cliente_nome=extracted.get("cliente_nome"),
        tipo_dano=extracted.get("tipo_dano"),
        updated_at=snapshot.updated_at,
    )


@router.get(
    "/queue",
    response_model=ReviewQueueResponse,
    summary="List claims awaiting human review",
)
async def list_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    claim_store: ClaimStore = Depends(get_claim_store),
) -> ReviewQueueResponse:
    """Return a paginated queue of claims with ``HUMAN_REVIEW`` status."""
    items = await claim_store.list_human_review_queue(limit=limit, offset=offset)
    logger.info(
        "Review queue fetched",
        extra={"count": len(items), "limit": limit, "offset": offset},
    )
    return ReviewQueueResponse(
        items=[_queue_item_from_snapshot(item) for item in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{claim_id}",
    response_model=ReviewDetailResponse,
    summary="Get full claim details for adjuster review",
)
async def get_review_detail(
    claim_id: str,
    claim_store: ClaimStore = Depends(get_claim_store),
) -> ReviewDetailResponse:
    """Return the persisted claim snapshot including triage and vision analysis."""
    snapshot = await claim_store.get(claim_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    return ReviewDetailResponse(
        claim_id=snapshot.claim_id,
        status=snapshot.status,
        payload=snapshot.payload,
        reviewer_note=snapshot.reviewer_note,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.post(
    "/{claim_id}/decision",
    response_model=ReviewDecisionResponse,
    summary="Record an adjuster approve/reject decision",
)
async def submit_review_decision(
    claim_id: str,
    body: ReviewDecisionRequest,
    claim_store: ClaimStore = Depends(get_claim_store),
) -> ReviewDecisionResponse:
    """Apply a human decision to a claim previously routed to review."""
    snapshot = await claim_store.get(claim_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    if snapshot.status != ClaimStatus.HUMAN_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Claim is not in HUMAN_REVIEW status (current: {snapshot.status}).",
        )

    new_status = ClaimStatus(body.decision)
    updated = await claim_store.apply_decision(claim_id, new_status, body.reviewer_note)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    logger.info(
        "Adjuster decision recorded",
        extra={
            "claim_id": claim_id,
            "decision": new_status,
            "reviewer_note": body.reviewer_note,
        },
    )

    return ReviewDecisionResponse(
        claim_id=updated.claim_id,
        status=updated.status,
        reviewer_note=updated.reviewer_note,
    )
