"""Public catalogue images (C3, OQ-10/11): processed variants only, rights recorded, withdrawal
unpublishes."""

import uuid
from datetime import UTC, date, datetime

from fastapi import UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.integrations.images import ImageError, process_public
from app.integrations.storage import Storage, new_key
from app.models import PublicMedia, User
from app.schemas.content import MediaOut
from app.services.events import record_audit
from app.services.uploads import MAX_FILE_BYTES, _read_limited

MEDIA_URL = "/api/v1/media/{key}"


def media_out(media: PublicMedia) -> MediaOut:
    return MediaOut(
        id=media.id,
        width=media.width,
        height=media.height,
        urls={size: MEDIA_URL.format(key=v["key"]) for size, v in media.variants.items()},
        alt=media.alt,
        status=media.status,
        rights_basis=media.rights_basis,
        rights_reference=media.rights_reference,
        consent_given_on=media.consent_given_on,
        consent_withdrawn_at=media.consent_withdrawn_at,
        created_at=media.created_at,
    )


def upload(
    db: Session,
    storage: Storage,
    admin: User,
    file: UploadFile,
    *,
    rights_basis: str,
    rights_reference: str | None,
    consent_given_on: date | None,
    personal_data_checked: bool,
    alt: dict[str, str],
) -> PublicMedia:
    if not personal_data_checked:
        raise AppError(
            "PERSONAL_DATA_NOT_CHECKED",
            "Confirm that the image shows no unauthorised personal data.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if rights_basis == "client_consent" and not (rights_reference and consent_given_on):
        raise AppError(
            "CONSENT_REQUIRED",
            "A client photo needs the consent reference and date.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    data = _read_limited(file)
    if not data:
        raise AppError("FILE_EMPTY", "The file is empty.")
    try:
        image = process_public(data)
    except ImageError as exc:
        code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE if exc.code == "UNSUPPORTED_FILE_TYPE" else 422
        raise AppError(exc.code, exc.message, code) from exc
    written: list[str] = []
    try:
        variants = {}
        for size, variant in image.variants.items():
            key = new_key()
            storage.put(key, variant.data)
            written.append(key)
            variants[size] = {"key": key, "width": variant.width, "height": variant.height}
        media = PublicMedia(
            storage_key=variants["1300"]["key"],
            variants=variants,
            width=image.width,
            height=image.height,
            alt={k: v.strip()[:200] for k, v in alt.items() if v and v.strip()},
            rights_basis=rights_basis,
            rights_reference=rights_reference,
            consent_given_on=consent_given_on,
            personal_data_checked=True,
            uploaded_by=admin.id,
        )
        db.add(media)
        db.flush()
        record_audit(
            db,
            "media.uploaded",
            "public_media",
            media.id,
            "user",
            admin.id,
            after={"rights_basis": rights_basis, "width": image.width},
        )
        db.commit()
    except BaseException:
        db.rollback()
        for key in written:
            storage.delete(key)
        raise
    return media


def _get(db: Session, media_id: uuid.UUID, lock: bool = False) -> PublicMedia:
    query = select(PublicMedia).where(PublicMedia.id == media_id)
    media = db.scalar(query.with_for_update() if lock else query)
    if media is None:
        raise AppError("NOT_FOUND", "Image not found.", status.HTTP_404_NOT_FOUND)
    return media


def list_media(db: Session) -> list[PublicMedia]:
    return list(db.scalars(select(PublicMedia).order_by(PublicMedia.created_at.desc())).all())


def archive(db: Session, admin: User, media_id: uuid.UUID, reason: str) -> PublicMedia:
    media = _get(db, media_id, lock=True)
    media.status = "archived"
    record_audit(db, "media.archived", "public_media", media.id, "user", admin.id, reason=reason)
    db.commit()
    return media


def withdraw_consent(db: Session, admin: User, media_id: uuid.UUID, reason: str) -> PublicMedia:
    """Takes the image out of every public version at once: the public route checks this on each request."""
    media = _get(db, media_id, lock=True)
    if media.consent_withdrawn_at is None:
        media.consent_withdrawn_at = datetime.now(UTC)
    media.status = "archived"
    record_audit(db, "media.consent_withdrawn", "public_media", media.id, "user", admin.id, reason=reason)
    db.commit()
    return media


def publishable_by_key(db: Session, key: str) -> PublicMedia | None:
    match = text(
        "jsonb_path_exists(variants, '$.*.key ? (@ == $k)', jsonb_build_object('k', CAST(:k AS text)))"
    )
    for media in db.scalars(select(PublicMedia).where(match.bindparams(k=key))):
        if media.publishable:
            return media
    return None


def publishable_ids(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, PublicMedia]:
    if not ids:
        return {}
    rows = db.scalars(select(PublicMedia).where(PublicMedia.id.in_(ids))).all()
    return {m.id: m for m in rows if m.publishable}


__all__ = ["MAX_FILE_BYTES"]
