"""Production-grade validation for claim image / document uploads."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import UploadFile

# 10 MiB hard limit — reject early to reduce DoS risk.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})

EXTENSION_MIME_TYPES: dict[str, frozenset[str]] = {
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".webp": frozenset({"image/webp"}),
    ".gif": frozenset({"image/gif"}),
}

# Magic-byte prefixes (and WebP structural check). Extension keyed.
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class FileValidationError(Exception):
    """Raised when an upload fails a validation rule."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Bytes and metadata that passed all upload validation rules."""

    filename: str
    content_type: str
    data: bytes


def sanitize_filename(filename: str) -> str:
    """Return a basename-only safe filename (blocks path traversal)."""
    if not filename or not filename.strip():
        raise FileValidationError(
            status_code=400,
            detail="Filename is required.",
        )

    # Normalize Windows and Unix separators, then take the final component.
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = basename.replace("\x00", "")
    basename = _UNSAFE_FILENAME_CHARS.sub("_", basename).strip("._")

    if not basename or basename in {".", ".."}:
        raise FileValidationError(
            status_code=400,
            detail="Filename is invalid after sanitization.",
        )

    return basename


def validate_extension(filename: str) -> str:
    """Ensure the filename extension is in the allowlist. Returns normalized ext."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise FileValidationError(
            status_code=400,
            detail=f"Unsupported file extension '{ext or '(none)'}'. Allowed: {allowed}.",
        )
    return ext


def validate_mime_type(content_type: str | None, extension: str) -> str:
    """Require declared MIME type to match the file extension allowlist entry."""
    allowed = EXTENSION_MIME_TYPES[extension]
    if not content_type or not content_type.strip():
        raise FileValidationError(
            status_code=400,
            detail="Content-Type is required and must match the file extension.",
        )

    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in allowed:
        expected = ", ".join(sorted(allowed))
        raise FileValidationError(
            status_code=400,
            detail=(
                f"Content-Type '{normalized}' does not match extension '{extension}'. "
                f"Expected: {expected}."
            ),
        )
    return normalized


def validate_magic_bytes(data: bytes, extension: str) -> None:
    """Verify file content magic numbers match the declared extension."""
    if not data:
        raise FileValidationError(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    if extension == ".webp":
        if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise FileValidationError(
                status_code=400,
                detail="File content does not match a WebP image (magic bytes).",
            )
        return

    prefixes = _MAGIC_PREFIXES.get(extension, ())
    if not any(data.startswith(prefix) for prefix in prefixes):
        raise FileValidationError(
            status_code=400,
            detail=f"File content does not match extension '{extension}' (magic bytes).",
        )


def validate_file_size(size_bytes: int) -> None:
    """Reject payloads larger than ``MAX_UPLOAD_BYTES`` (HTTP 413)."""
    if size_bytes > MAX_UPLOAD_BYTES:
        raise FileValidationError(
            status_code=413,
            detail=f"File exceeds maximum size of {MAX_UPLOAD_BYTES} bytes (10 MB).",
        )


async def read_upload_with_size_limit(upload: UploadFile) -> bytes:
    """Read an ``UploadFile`` in chunks, aborting with 413 if over the limit."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        validate_file_size(total)
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise FileValidationError(
            status_code=400,
            detail="Uploaded file is empty.",
        )
    return data


async def validate_upload(upload: UploadFile) -> ValidatedUpload:
    """Run all upload validation rules and return sanitized metadata + bytes."""
    if not upload.filename:
        raise FileValidationError(
            status_code=400,
            detail="Filename is required.",
        )

    safe_name = sanitize_filename(upload.filename)
    extension = validate_extension(safe_name)
    content_type = validate_mime_type(upload.content_type, extension)
    data = await read_upload_with_size_limit(upload)
    validate_magic_bytes(data, extension)

    return ValidatedUpload(
        filename=safe_name,
        content_type=content_type,
        data=data,
    )
