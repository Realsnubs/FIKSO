"""Admin: commercial terms (C1), public images (C3), page content (C4). Admin role only, every write
audited."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import AdminUser, DbSession
from app.core.ratelimit import rate_limit
from app.integrations.storage import get_public_storage
from app.schemas.commercial import CommercialTermsIn, CommercialTermsOut
from app.schemas.content import (
    ContentActionIn,
    ContentDraftIn,
    ContentListItem,
    ContentOut,
    ContentSlugIn,
    MediaArchiveIn,
    MediaOut,
)
from app.services import commercial, content, media, public_catalogue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/commercial-terms")
def list_terms(db: DbSession, _: AdminUser) -> list[CommercialTermsOut]:
    return [commercial.out(t) for t in commercial.history(db)]


@router.post("/commercial-terms", status_code=status.HTTP_201_CREATED)
def create_terms(db: DbSession, admin: AdminUser, body: CommercialTermsIn) -> CommercialTermsOut:
    terms = commercial.create(db, admin, body)
    public_catalogue.clear_cache()
    return commercial.out(terms)


@router.get("/media")
def list_media(db: DbSession, _: AdminUser) -> list[MediaOut]:
    return [media.media_out(m) for m in media.list_media(db)]


@router.post(
    "/media",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload"))],
)
def upload_media(
    db: DbSession,
    admin: AdminUser,
    file: Annotated[UploadFile, File()],
    rights_basis: Annotated[Literal["own", "client_consent", "licence"], Form()],
    personal_data_checked: Annotated[bool, Form()],
    rights_reference: Annotated[str | None, Form(max_length=300)] = None,
    consent_given_on: Annotated[date | None, Form()] = None,
    alt_lv: Annotated[str | None, Form(max_length=200)] = None,
    alt_en: Annotated[str | None, Form(max_length=200)] = None,
    alt_ru: Annotated[str | None, Form(max_length=200)] = None,
) -> MediaOut:
    item = media.upload(
        db,
        get_public_storage(),
        admin,
        file,
        rights_basis=rights_basis,
        rights_reference=rights_reference,
        consent_given_on=consent_given_on,
        personal_data_checked=personal_data_checked,
        alt={"lv": alt_lv or "", "en": alt_en or "", "ru": alt_ru or ""},
    )
    return media.media_out(item)


@router.post("/media/{media_id}/archive")
def archive_media(db: DbSession, admin: AdminUser, media_id: uuid.UUID, body: MediaArchiveIn) -> MediaOut:
    item = media.archive(db, admin, media_id, body.reason)
    public_catalogue.clear_cache()
    return media.media_out(item)


@router.post("/media/{media_id}/withdraw-consent")
def withdraw_consent(db: DbSession, admin: AdminUser, media_id: uuid.UUID, body: MediaArchiveIn) -> MediaOut:
    item = media.withdraw_consent(db, admin, media_id, body.reason)
    public_catalogue.clear_cache()
    return media.media_out(item)


@router.get("/content")
def list_content(db: DbSession, _: AdminUser) -> list[ContentListItem]:
    return content.list_pages(db)


@router.get("/content/{specialisation_id}")
def get_content(db: DbSession, _: AdminUser, specialisation_id: uuid.UUID) -> ContentOut:
    return content.detail(db, specialisation_id)


@router.put("/content/{specialisation_id}/draft")
def save_draft(
    db: DbSession, admin: AdminUser, specialisation_id: uuid.UUID, body: ContentDraftIn
) -> ContentOut:
    return content.save_draft(db, admin, specialisation_id, body.data, body.expected_version)


@router.post("/content/{specialisation_id}/publish")
def publish(
    db: DbSession, admin: AdminUser, specialisation_id: uuid.UUID, body: ContentActionIn
) -> ContentOut:
    result = content.publish(db, admin, specialisation_id, body.expected_version)
    public_catalogue.clear_cache()
    return result


@router.post("/content/{specialisation_id}/unpublish")
def unpublish(
    db: DbSession, admin: AdminUser, specialisation_id: uuid.UUID, body: ContentActionIn
) -> ContentOut:
    result = content.unpublish(db, admin, specialisation_id, body.expected_version)
    public_catalogue.clear_cache()
    return result


@router.post("/content/{specialisation_id}/versions/{version_id}/restore")
def restore(
    db: DbSession,
    admin: AdminUser,
    specialisation_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ContentActionIn,
) -> ContentOut:
    return content.restore(db, admin, specialisation_id, version_id, body.expected_version)


@router.put("/content/{specialisation_id}/slug")
def set_slug(
    db: DbSession, admin: AdminUser, specialisation_id: uuid.UUID, body: ContentSlugIn
) -> ContentOut:
    result = content.set_slug(db, admin, specialisation_id, body.slug, body.expected_version)
    public_catalogue.clear_cache()
    return result
