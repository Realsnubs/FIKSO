"""Validation and storage of uploaded evidence files (R-MST-15, Q-26).

The real format is detected from the file's first bytes; the client's file name and Content-Type are ignored
and never stored. Files are written to storage only by `store_attachments`, inside the request that creates
the owning record, and are removed again if that record is not committed.
"""

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.integrations.storage import Storage, new_key
from app.models import Attachment

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5
# Long enough that an upload still waiting for its commit is never mistaken for an orphan.
ORPHAN_AGE = timedelta(hours=24)
_CHUNK = 64 * 1024
HEIC_BRANDS = {b"heic", b"heix", b"mif1", b"msf1"}


def detect_mime(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS:
        return "image/heic"
    return None


@dataclass(frozen=True)
class ValidFile:
    data: bytes
    mime_type: str
    sha256: str


def _read_limited(upload: UploadFile) -> bytes:
    chunks, size = [], 0
    # Synchronous read of the spooled file: upload endpoints are sync and run in the threadpool like the rest.
    while chunk := upload.file.read(_CHUNK):
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise AppError(
                "FILE_TOO_LARGE",
                "Each file may be at most 10 MB.",
                status.HTTP_413_CONTENT_TOO_LARGE,
                {"max_bytes": MAX_FILE_BYTES},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def validate_files(uploads: list[UploadFile]) -> list[ValidFile]:
    """All files are checked before anything is written, so a bad file never leaves others behind."""
    if len(uploads) > MAX_FILES:
        raise AppError("TOO_MANY_FILES", "At most 5 files per submission.", details={"max_files": MAX_FILES})
    result = []
    for index, upload in enumerate(uploads):
        data = _read_limited(upload)
        if not data:
            raise AppError("FILE_EMPTY", "The file is empty.", details={"index": index})
        mime_type = detect_mime(data)
        if mime_type is None:
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                "Allowed formats: PDF, JPEG, PNG, WebP, HEIC.",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                {"index": index},
            )
        result.append(ValidFile(data, mime_type, hashlib.sha256(data).hexdigest()))
    return result


@contextmanager
def store_attachments(
    db: Session,
    storage: Storage,
    files: list[ValidFile],
    *,
    owner_user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
) -> Iterator[list[Attachment]]:
    """Write the files and add their rows; the caller commits inside the block.

    If the block raises (validation, constraint, commit failure), the objects written here are deleted again,
    so no file outlives a failed submission. A crash between write and commit is covered by
    `cleanup-orphan-files`.
    """
    written: list[str] = []
    try:
        attachments = []
        for file in files:
            key = new_key()
            storage.put(key, file.data)
            written.append(key)
            attachment = Attachment(
                owner_user_id=owner_user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                storage_key=key,
                mime_type=file.mime_type,
                size_bytes=len(file.data),
                sha256=file.sha256,
            )
            db.add(attachment)
            attachments.append(attachment)
        yield attachments
    except BaseException:
        db.rollback()
        for key in written:
            storage.delete(key)
        raise


def cleanup_orphans(db: Session, storage: Storage, now: datetime | None = None) -> int:
    """Delete stored objects that have no attachment row and are older than ORPHAN_AGE (crash leftovers).

    Objects with a row are never touched: their removal belongs to the retention policy (Q-12/Q-27).
    """
    cutoff = (now or datetime.now(UTC)) - ORPHAN_AGE
    candidates = [key for key, written in storage.objects() if written < cutoff]
    if not candidates:
        return 0
    known = set(db.scalars(select(Attachment.storage_key).where(Attachment.storage_key.in_(candidates))))
    orphans = [key for key in candidates if key not in known]
    for key in orphans:
        storage.delete(key)
    return len(orphans)
