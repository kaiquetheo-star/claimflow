"""File upload endpoints backed by the storage strategy pattern."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from claimflow.api.dependencies import require_api_key
from claimflow.api.file_validation import FileValidationError, validate_upload
from claimflow.core.logging import get_logger
from claimflow.tools.factory import get_storage_client

router = APIRouter(prefix="/uploads", tags=["uploads"])
logger = get_logger(__name__)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a claim document",
    dependencies=[Depends(require_api_key)],
)
async def upload_file(
    file: UploadFile = File(
        ...,
        description="Image to store (.jpg, .jpeg, .png, .webp, .gif; max 10 MB).",
    ),
) -> dict[str, str]:
    """Accept a multipart image upload and persist it via the active storage backend."""
    try:
        validated = await validate_upload(file)
    except FileValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    storage = get_storage_client()

    try:
        url = await storage.upload_file(validated.data, validated.filename)
    except NotImplementedError as exc:
        logger.error(
            "Storage backend not available",
            extra={"filename": validated.filename, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    logger.info(
        "Upload completed",
        extra={
            "filename": validated.filename,
            "url": url,
            "size_bytes": len(validated.data),
            "content_type": validated.content_type,
        },
    )

    return {
        "filename": validated.filename,
        "url": url,
        "content_type": validated.content_type,
    }
