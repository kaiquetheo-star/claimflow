"""Human-review dashboard API for adjuster workflows."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from langgraph.graph.state import CompiledStateGraph

from claimflow.agents.graph import is_awaiting_human_review, resume_with_human_decision
from claimflow.agents.states import ClaimStatus
from claimflow.api.dependencies import get_claim_graph, get_claim_store, require_api_key
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

# Only claims paused for adjuster review can receive a decision / graph resume.
_DECIDABLE_STATUSES: frozenset[ClaimStatus] = frozenset({ClaimStatus.HUMAN_REVIEW})


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


def _has_recorded_decision(payload: dict) -> bool:
    decision = payload.get("human_decision")
    if isinstance(decision, dict) and decision.get("decision"):
        return True
    if isinstance(decision, str) and decision.strip():
        return True
    return False


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
    graph: CompiledStateGraph = Depends(get_claim_graph),
) -> ReviewDetailResponse:
    """Return the persisted claim snapshot including interrupt / resume flags."""
    snapshot = await claim_store.get(claim_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    payload = dict(snapshot.payload)
    paused = await is_awaiting_human_review(graph, claim_id)
    if paused:
        payload["awaiting_human_decision"] = True
        payload["graph_interrupted"] = True

    return ReviewDetailResponse(
        claim_id=snapshot.claim_id,
        status=snapshot.status,
        payload=payload,
        reviewer_note=snapshot.reviewer_note,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.post(
    "/{claim_id}/decision",
    response_model=ReviewDecisionResponse,
    summary="Record an adjuster approve/reject decision and resume LangGraph",
    dependencies=[Depends(require_api_key)],
)
async def submit_review_decision(
    claim_id: str,
    body: ReviewDecisionRequest,
    claim_store: ClaimStore = Depends(get_claim_store),
    graph: CompiledStateGraph = Depends(get_claim_graph),
) -> ReviewDecisionResponse:
    """Apply a human decision: resume the interrupted graph when a checkpoint exists.

    Flow:
      1. Validate claim is in ``HUMAN_REVIEW`` and has no prior decision.
      2. If LangGraph is paused at ``interrupt_before=['human_review']``, call
         ``aupdate_state`` + ``ainvoke`` to resume.
      3. Persist the final decision on the claim store (fallback if checkpoint lost).
    """
    snapshot = await claim_store.get(claim_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    if snapshot.status not in _DECIDABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Claim cannot be decided in status {snapshot.status}.",
        )

    if _has_recorded_decision(snapshot.payload):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision already recorded for this claim.",
        )

    new_status = ClaimStatus(body.decision)
    decided_at = datetime.now(UTC)
    graph_resumed = False

    if await is_awaiting_human_review(graph, claim_id):
        try:
            graph_result = await resume_with_human_decision(
                graph,
                claim_id,
                decision=new_status,
                reviewer_note=body.reviewer_note,
                analyst_id=body.analyst_id,
            )
            graph_resumed = True
            # Keep store in sync with final graph values + analyst metadata.
            await claim_store.save_result(
                claim_id,
                ClaimStatus(graph_result.get("status", new_status)),
                {
                    **snapshot.payload,
                    **graph_result,
                    "awaiting_human_decision": False,
                    "graph_interrupted": False,
                    "graph_resumed": True,
                },
            )
        except ValueError as exc:
            logger.warning(
                "LangGraph resume unavailable; falling back to claim-store decision",
                extra={"claim_id": claim_id, "error": str(exc)},
            )

    updated = await claim_store.apply_decision(
        claim_id,
        new_status,
        body.reviewer_note,
        body.analyst_id,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found.")

    logger.info(
        "Human analyst decision recorded",
        extra={
            "claim_id": claim_id,
            "decision": new_status.value,
            "analyst_id": body.analyst_id,
            "reviewer_note": body.reviewer_note,
            "decided_at": decided_at.isoformat(),
            "graph_resumed": graph_resumed,
        },
    )

    return ReviewDecisionResponse(
        claim_id=updated.claim_id,
        status=updated.status,
        reviewer_note=updated.reviewer_note,
        analyst_id=body.analyst_id,
        decided_at=decided_at,
    )
