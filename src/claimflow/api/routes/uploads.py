"""File upload endpoints backed by the storage strategy pattern."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from claimflow.core.logging import get_logger
from claimflow.tools.factory import get_storage_client

router = APIRouter(prefix="/uploads", tags=["uploads"])
logger = get_logger(__name__)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a claim document",
)
async def upload_file(
    file: UploadFile = File(..., description="Document to store (PDF, image, etc.)."),
) -> dict[str, str]:
    """Accept a multipart file upload and persist it via the active storage backend."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    storage = get_storage_client()

    try:
        url = await storage.upload_file(file_bytes, file.filename)
    except NotImplementedError as exc:
        logger.error(
            "Storage backend not available",
            extra={"filename": file.filename, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    logger.info(
        "Upload completed",
        extra={"filename": file.filename, "url": url, "size_bytes": len(file_bytes)},
    )

    return {
        "filename": file.filename,
        "url": url,
        "content_type": file.content_type or "application/octet-stream",
    }
