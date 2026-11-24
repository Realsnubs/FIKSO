"""Versioned page content of specialisations (C4). Admin only; the catalogue itself is never modified."""

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import (
    CatalogueCategory,
    CatalogueContent,
    CatalogueContentVersion,
    CatalogueSpecialisation,
    ContentSlugRedirect,
    PublicMedia,
    User,
)
from app.schemas.content import ContentData, ContentListItem, ContentOut, ContentVersionOut
from app.services.events import record_audit, record_event

_TRANSLIT = str.maketrans(
    {
        "ā": "a",
        "č": "c",
        "ē": "e",
        "ģ": "g",
        "ī": "i",
        "ķ": "k",
        "ļ": "l",
        "ņ": "n",
        "š": "s",
        "ū": "u",
        "ž": "z",
    }
)


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKC", name.lower()).translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80] or "pakalpojums"


def _version_out(row: CatalogueContentVersion) -> ContentVersionOut:
    return ContentVersionOut(
        id=row.id,
        version_no=row.version_no,
        state=row.state,
        data=ContentData.model_validate(row.data),
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
    )


def _spec(db: Session, specialisation_id: uuid.UUID) -> CatalogueSpecialisation:
    spec = db.get(CatalogueSpecialisation, specialisation_id)
    if spec is None:
        raise AppError("NOT_FOUND", "Specialisation not found.", status.HTTP_404_NOT_FOUND)
    return spec


def _slug_taken(db: Session, slug: str, own_id: uuid.UUID | None) -> bool:
    owner = db.scalar(select(CatalogueContent.id).where(CatalogueContent.slug == slug))
    if owner is not None and owner != own_id:
        return True
    redirect = db.get(ContentSlugRedirect, slug)
    return redirect is not None and redirect.content_id != own_id


def _ensure(db: Session, spec: CatalogueSpecialisation) -> CatalogueContent:
    content = db.scalar(
        select(CatalogueContent)
        .where(CatalogueContent.entity_type == "specialisation", CatalogueContent.entity_id == spec.id)
        .with_for_update()
    )
    if content is None:
        base = slugify(spec.name)
        slug, n = base, 2
        while _slug_taken(db, slug, None):
            slug, n = f"{base}-{n}", n + 1
        content = CatalogueContent(entity_type="specialisation", entity_id=spec.id, slug=slug)
        db.add(content)
        db.flush()
    return content


def _check_version(content: CatalogueContent, expected: int) -> None:
    if content.version != expected:
        raise AppError(
            "VERSION_CONFLICT",
            "The page was changed meanwhile. Reload and try again.",
            status.HTTP_409_CONFLICT,
            {"current_version": content.version},
        )


def _versions(db: Session, content_id: uuid.UUID) -> list[CatalogueContentVersion]:
    return list(
        db.scalars(
            select(CatalogueContentVersion)
            .where(CatalogueContentVersion.content_id == content_id)
            .order_by(CatalogueContentVersion.version_no.desc())
        ).all()
    )


def detail(db: Session, specialisation_id: uuid.UUID) -> ContentOut:
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    db.commit()
    versions = _versions(db, content.id)
    draft = next((v for v in versions if v.state == "draft"), None)
    published = next((v for v in versions if v.id == content.published_version_id), None)
    return ContentOut(
        id=content.id,
        specialisation_id=spec.id,
        specialisation_name=spec.name,
        slug=content.slug,
        version=content.version,
        published_version_no=published.version_no if published else None,
        draft=_version_out(draft) if draft else None,
        published=_version_out(published) if published else None,
        history=[_version_out(v) for v in versions if v.state != "draft"][:20],
    )


def list_pages(db: Session) -> list[ContentListItem]:
    specs = db.scalars(
        select(CatalogueSpecialisation)
        .options(selectinload(CatalogueSpecialisation.category))
        .where(CatalogueSpecialisation.status != "archived")
        .join(CatalogueCategory)
        .order_by(
            CatalogueCategory.sort_order, CatalogueSpecialisation.sort_order, CatalogueSpecialisation.name
        )
    ).all()
    contents = {
        c.entity_id: c
        for c in db.scalars(select(CatalogueContent).where(CatalogueContent.entity_type == "specialisation"))
    }
    drafts = set(
        db.scalars(select(CatalogueContentVersion.content_id).where(CatalogueContentVersion.state == "draft"))
    )
    items = []
    for spec in specs:
        content = contents.get(spec.id)
        items.append(
            ContentListItem(
                specialisation_id=spec.id,
                specialisation_name=spec.name,
                category_name=spec.category.name,
                status=spec.status,
                content_id=content.id if content else None,
                slug=content.slug if content else None,
                has_draft=bool(content and content.id in drafts),
                published=bool(content and content.published_version_id),
            )
        )
    return items


def _check_media(db: Session, data: ContentData, require_ready: bool) -> None:
    ids = {g.media_id for g in data.gallery} | ({data.card_image} if data.card_image else set())
    if not ids:
        return
    found = {m.id: m for m in db.scalars(select(PublicMedia).where(PublicMedia.id.in_(ids)))}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise AppError(
            "CONTENT_INVALID", "Unknown image.", status.HTTP_422_UNPROCESSABLE_CONTENT, {"media": missing}
        )
    if require_ready:
        not_ready = [str(i) for i, m in found.items() if not m.publishable]
        if not_ready:
            raise AppError(
                "MEDIA_NOT_READY",
                "An image is archived or its consent was withdrawn.",
                status.HTTP_409_CONFLICT,
                {"media": not_ready},
            )


def _check_services(spec: CatalogueSpecialisation, data: ContentData) -> None:
    own = {s.id for s in spec.services}
    unknown = [str(i) for i in data.services if i not in own]
    if unknown:
        raise AppError(
            "CONTENT_INVALID",
            "A service does not belong to this specialisation.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"services": unknown},
        )


def save_draft(
    db: Session, admin: User, specialisation_id: uuid.UUID, data: ContentData, expected_version: int
) -> ContentOut:
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    _check_version(content, expected_version)
    _check_services(spec, data)
    _check_media(db, data, require_ready=False)
    payload: dict[str, Any] = data.model_dump(mode="json", exclude_none=True)
    draft = db.scalar(
        select(CatalogueContentVersion).where(
            CatalogueContentVersion.content_id == content.id, CatalogueContentVersion.state == "draft"
        )
    )
    if draft is None:
        last = db.scalar(
            select(func.max(CatalogueContentVersion.version_no)).where(
                CatalogueContentVersion.content_id == content.id
            )
        )
        draft = CatalogueContentVersion(
            content_id=content.id,
            version_no=(last or 0) + 1,
            state="draft",
            data=payload,
            created_by=admin.id,
        )
        db.add(draft)
    else:
        draft.data = payload
        draft.updated_at = datetime.now(UTC)
    content.version += 1
    record_audit(db, "content.draft_saved", "catalogue_content", content.id, "user", admin.id)
    db.commit()
    return detail(db, specialisation_id)


def publish(db: Session, admin: User, specialisation_id: uuid.UUID, expected_version: int) -> ContentOut:
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    _check_version(content, expected_version)
    draft = db.scalar(
        select(CatalogueContentVersion).where(
            CatalogueContentVersion.content_id == content.id, CatalogueContentVersion.state == "draft"
        )
    )
    if draft is None:
        raise AppError("NOTHING_TO_PUBLISH", "There is no draft to publish.", status.HTTP_409_CONFLICT)
    data = ContentData.model_validate(draft.data)
    _check_services(spec, data)
    _check_media(db, data, require_ready=True)
    if content.published_version_id:
        previous = db.get(CatalogueContentVersion, content.published_version_id)
        if previous is not None:
            previous.state = "superseded"
    now = datetime.now(UTC)
    draft.state, draft.published_at, draft.published_by = "published", now, admin.id
    content.published_version_id = draft.id
    content.version += 1
    record_audit(
        db,
        "content.published",
        "catalogue_content",
        content.id,
        "user",
        admin.id,
        after={"version_no": draft.version_no},
    )
    record_event(
        db,
        "content.published",
        "catalogue_content",
        content.id,
        "user",
        admin.id,
        {"version_no": draft.version_no},
    )
    db.commit()
    return detail(db, specialisation_id)


def unpublish(db: Session, admin: User, specialisation_id: uuid.UUID, expected_version: int) -> ContentOut:
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    _check_version(content, expected_version)
    if content.published_version_id is None:
        raise AppError("NOT_PUBLISHED", "The page is not published.", status.HTTP_409_CONFLICT)
    previous = db.get(CatalogueContentVersion, content.published_version_id)
    if previous is not None:
        previous.state = "superseded"
    content.published_version_id = None
    content.version += 1
    record_audit(db, "content.unpublished", "catalogue_content", content.id, "user", admin.id)
    record_event(db, "content.unpublished", "catalogue_content", content.id, "user", admin.id)
    db.commit()
    return detail(db, specialisation_id)


def restore(
    db: Session, admin: User, specialisation_id: uuid.UUID, version_id: uuid.UUID, expected_version: int
) -> ContentOut:
    """Copies an earlier version into the draft; published history itself is never changed."""
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    source = db.get(CatalogueContentVersion, version_id)
    if source is None or source.content_id != content.id:
        raise AppError("NOT_FOUND", "Version not found.", status.HTTP_404_NOT_FOUND)
    record_audit(
        db,
        "content.restored",
        "catalogue_content",
        content.id,
        "user",
        admin.id,
        after={"from_version": source.version_no},
    )
    return save_draft(db, admin, specialisation_id, ContentData.model_validate(source.data), expected_version)


def set_slug(
    db: Session, admin: User, specialisation_id: uuid.UUID, slug: str, expected_version: int
) -> ContentOut:
    spec = _spec(db, specialisation_id)
    content = _ensure(db, spec)
    _check_version(content, expected_version)
    if slug != content.slug:
        if _slug_taken(db, slug, content.id):
            raise AppError("SLUG_TAKEN", "This address is already used.", status.HTTP_409_CONFLICT)
        own_redirect = db.get(ContentSlugRedirect, slug)
        if own_redirect is not None:
            db.delete(own_redirect)
        db.add(ContentSlugRedirect(old_slug=content.slug, content_id=content.id))
        record_audit(
            db,
            "content.slug_changed",
            "catalogue_content",
            content.id,
            "user",
            admin.id,
            before={"slug": content.slug},
            after={"slug": slug},
        )
        content.slug = slug
        content.version += 1
        db.commit()
    return detail(db, specialisation_id)


def published_data(db: Session) -> dict[uuid.UUID, tuple[CatalogueContent, ContentData | None]]:
    """Every specialisation's content row with its published data (None when not published)."""
    rows = db.execute(
        select(CatalogueContent, CatalogueContentVersion)
        .outerjoin(
            CatalogueContentVersion, CatalogueContentVersion.id == CatalogueContent.published_version_id
        )
        .where(CatalogueContent.entity_type == "specialisation")
    ).all()
    return {
        content.entity_id: (content, ContentData.model_validate(version.data) if version else None)
        for content, version in rows
    }


def resolve_slug(db: Session, slug: str) -> tuple[CatalogueContent | None, str | None]:
    """(content, None) for the current slug; (None, new_slug) for a redirected old slug; (None, None)
    unknown."""
    content = db.scalar(select(CatalogueContent).where(CatalogueContent.slug == slug))
    if content is not None:
        return content, None
    redirect = db.get(ContentSlugRedirect, slug)
    if redirect is not None:
        target = db.get(CatalogueContent, redirect.content_id)
        if target is not None:
            return None, target.slug
    return None, None
