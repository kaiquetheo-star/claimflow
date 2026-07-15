"""Claim submission endpoints."""

from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from langgraph.graph.state import CompiledStateGraph

from claimflow.agents.graph import is_awaiting_human_review, thread_config
from claimflow.agents.states import ClaimStatus
from claimflow.api.dependencies import get_claim_graph, get_claim_store, require_api_key
from claimflow.api.file_validation import FileValidationError, validate_upload
from claimflow.core.context import bind_claim_correlation
from claimflow.core.i18n import set_request_language
from claimflow.core.logging import get_logger
from claimflow.core.metrics import metrics
from claimflow.models.schemas import ClaimResponse, ClaimSubmissionRequest
from claimflow.services.claim_store import ClaimStore
from claimflow.tools.factory import get_storage_client
from claimflow.tools.storage_interface import BaseStorage

router = APIRouter(prefix="/claims", tags=["claims"])
logger = get_logger(__name__)


async def _resolve_image_path(filename: str, storage: BaseStorage) -> tuple[str, bool]:
    """Materialise a local path for Qwen-VL (download from OSS when needed).

    Returns:
        ``(local_path, is_temporary)``. Temporary files are deleted after the
        graph finishes processing the claim.
    """
    return await storage.materialize_local_path(filename)


def _cleanup_temp_image(path: str | None, *, is_temporary: bool) -> None:
    """Best-effort removal of a temp image downloaded from remote storage."""
    if not path or not is_temporary:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "Failed to delete temporary vision image",
            extra={"path": path, "error": str(exc)},
        )


def _build_claim_response(result: dict[str, Any]) -> ClaimResponse:
    error = result.get("error") or None
    awaiting = bool(result.get("awaiting_human_decision"))
    interrupted = bool(result.get("graph_interrupted"))
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
        requires_human_review=result.get("requires_human_review", False) or awaiting,
        awaiting_human_decision=awaiting,
        graph_interrupted=interrupted,
        error=error if error else None,
    )


@router.post(
    "/submit",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a claim for autonomous processing via LangGraph",
    dependencies=[Depends(require_api_key)],
)
async def submit_claim(
    request: Request,
    claim_id: str = Form(..., description="Unique claim identifier."),
    raw_input_text: str = Form(..., description="Raw claim text (e.g. email body)."),
    language: str = Form(
        default="en",
        pattern="^(en|pt|es)$",
        description="UI/LLM response language: en (default), pt, or es.",
    ),
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
    submission = ClaimSubmissionRequest(
        claim_id=claim_id,
        raw_input_text=raw_input_text,
        language=language,  # type: ignore[arg-type]
    )
    resolved_language = set_request_language(submission.language)
    bind_claim_correlation(submission.claim_id)
    metrics.record_submission()
    log = get_logger(__name__, claim_id=submission.claim_id)
    log.info(
        "Claim submission received",
        extra={"endpoint": "/claims/submit", "language": resolved_language},
    )

    image_path: str | None = None
    image_is_temporary = False
    processing_started = perf_counter()

    if image is not None and image.filename:
        try:
            validated = await validate_upload(image)
        except FileValidationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

        storage = get_storage_client()
        stored_name = f"{submission.claim_id}_{validated.filename}"
        try:
            await storage.upload_file(validated.data, stored_name)
            image_path, image_is_temporary = await _resolve_image_path(stored_name, storage)
        except Exception as exc:
            log.error(
                "Claim image storage/materialisation failed",
                extra={"claim_id": submission.claim_id, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to store or prepare claim image for analysis.",
            ) from exc

        log.info(
            "Claim image stored",
            extra={
                "claim_id": submission.claim_id,
                "filename": stored_name,
                "image_path": image_path,
                "image_is_temporary": image_is_temporary,
                "size_bytes": len(validated.data),
            },
        )

    initial_state: dict = {
        "claim_id": submission.claim_id,
        "raw_input": submission.raw_input_text,
        "language": resolved_language,
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
        "awaiting_human_decision": False,
        "graph_interrupted": False,
        "human_decision": None,
        "reviewer_note": None,
        "analyst_id": None,
    }
    run_config = thread_config(submission.claim_id)

    try:
        try:
            result = dict(await graph.ainvoke(initial_state, config=run_config))
        except Exception as exc:
            log.error(
                "Claim graph invocation failed",
                extra={"claim_id": submission.claim_id, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Claim processing failed.",
            ) from exc

        interrupted = await is_awaiting_human_review(graph, submission.claim_id)
        if interrupted:
            result["status"] = ClaimStatus.HUMAN_REVIEW
            result["awaiting_human_decision"] = True
            result["graph_interrupted"] = True
            result["requires_human_review"] = True
            log.info(
                "LangGraph paused before human_review (interrupt_before)",
                extra={"claim_id": submission.claim_id, "next_node": "human_review"},
            )

        await claim_store.save_result(
            claim_id=submission.claim_id,
            status=result["status"],
            payload=dict(result),
        )

        elapsed = perf_counter() - processing_started
        metrics.record_processing_time(elapsed)
        final_status = result.get("status")
        if hasattr(final_status, "value"):
            metrics.record_outcome(str(final_status.value))
        elif final_status is not None:
            metrics.record_outcome(str(final_status))

        log.info(
            "Claim processing completed",
            extra={
                "claim_id": submission.claim_id,
                "final_status": result.get("status"),
                "awaiting_human_decision": result.get("awaiting_human_decision", False),
                "graph_interrupted": result.get("graph_interrupted", False),
                "risk_score": result.get("risk_score", 0.0),
                "consistency_score": result.get("consistency_score"),
                "duration_ms": round(elapsed * 1000, 2),
                "checkpoint_backend": getattr(
                    request.app.state, "checkpoint_backend", "unknown"
                ),
            },
        )

        return _build_claim_response(result)
    finally:
        _cleanup_temp_image(image_path, is_temporary=image_is_temporary)
