"""Claim submission endpoints."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from langgraph.graph.state import CompiledStateGraph

from claimflow.agents.states import ClaimStatus
from claimflow.api.dependencies import get_claim_graph, get_claim_store
from claimflow.core.logging import get_logger
from claimflow.models.schemas import ClaimResponse, ClaimSubmissionRequest
from claimflow.services.claim_store import ClaimStore
from claimflow.tools.factory import get_storage_client
from claimflow.tools.local_storage import LocalStorage

router = APIRouter(prefix="/claims", tags=["claims"])
logger = get_logger(__name__)

ALLOWED_IMAGE_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
)


async def _resolve_image_path(filename: str, storage: object) -> str:
    """Return a local filesystem path suitable for Qwen-VL analysis."""
    if isinstance(storage, LocalStorage):
        return str(storage.resolve_local_path(filename))
    return filename


def _build_claim_response(result: dict[str, Any]) -> ClaimResponse:
    error = result.get("error") or None
    return ClaimResponse(
        claim_id=result["claim_id"],
        status=result["status"],
        extracted_data=result.get("extracted_data") or {},
        image_analysis=result.get("image_analysis"),
        consistency_score=result.get("consistency_score"),
        fraud_risk_score=result.get("fraud_risk_score", 0.0),
        severity_score=result.get("severity_score", 0.0),
        risk_score=result.get("risk_score", 0.0),
        risk_assessment=result.get("risk_assessment") or {},
        requires_human_review=result.get("requires_human_review", False),
        error=error if error else None,
    )


@router.post(
    "/submit",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a claim for autonomous processing via LangGraph",
)
async def submit_claim(
    request: Request,
    claim_id: str = Form(..., description="Unique claim identifier."),
    raw_input_text: str = Form(..., description="Raw claim text (e.g. email body)."),
    image: UploadFile | None = File(
        default=None,
        description="Optional claim photo for Qwen-VL visual analysis.",
    ),
    graph: CompiledStateGraph = Depends(get_claim_graph),
    claim_store: ClaimStore = Depends(get_claim_store),
) -> ClaimResponse:
    """Run the full claim pipeline and return the final agent state.

    Accepts ``multipart/form-data`` with optional image upload. State is
    checkpointed via LangGraph using ``claim_id`` as ``thread_id``.
    """
    submission = ClaimSubmissionRequest(claim_id=claim_id, raw_input_text=raw_input_text)
    log = get_logger(__name__, claim_id=submission.claim_id)
    log.info("Claim submission received", extra={"endpoint": "/claims/submit"})

    image_path: str | None = None

    if image is not None and image.filename:
        if image.content_type and image.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported image content type: {image.content_type}",
            )

        file_bytes = await image.read()
        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded image is empty.",
            )

        storage = get_storage_client()
        stored_name = f"{submission.claim_id}_{Path(image.filename).name}"
        await storage.upload_file(file_bytes, stored_name)
        image_path = await _resolve_image_path(stored_name, storage)

        log.info(
            "Claim image stored",
            extra={
                "claim_id": submission.claim_id,
                "filename": stored_name,
                "image_path": image_path,
                "size_bytes": len(file_bytes),
            },
        )

    initial_state: dict = {
        "claim_id": submission.claim_id,
        "raw_input": submission.raw_input_text,
        "image_path": image_path,
        "extracted_data": {},
        "image_analysis": None,
        "consistency_score": None,
        "fraud_risk_score": 0.0,
        "severity_score": 0.0,
        "risk_score": 0.0,
        "requires_human_review": False,
        "risk_assessment": {},
        "tool_calls_made": [],
        "weather_verification": None,
        "system_error": False,
        "status": ClaimStatus.PENDING,
        "error": "",
        "error_message": "",
    }
    run_config = {"configurable": {"thread_id": submission.claim_id}}

    try:
        result = await graph.ainvoke(initial_state, config=run_config)
    except Exception as exc:
        log.error(
            "Claim graph invocation failed",
            extra={"claim_id": submission.claim_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Claim processing failed.",
        ) from exc

    await claim_store.save_result(
        claim_id=submission.claim_id,
        status=result["status"],
        payload=dict(result),
    )

    log.info(
        "Claim processing completed",
        extra={
            "claim_id": submission.claim_id,
            "final_status": result.get("status"),
            "risk_score": result.get("risk_score", 0.0),
            "consistency_score": result.get("consistency_score"),
            "checkpoint_backend": getattr(request.app.state, "checkpoint_backend", "unknown"),
        },
    )

    return _build_claim_response(result)
