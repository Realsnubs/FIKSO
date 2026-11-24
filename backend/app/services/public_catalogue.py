"""Public catalogue (C2, C6): only orderable services, never internal fields or master data (OQ-1, OQ-4)."""

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import CatalogueCategory, CatalogueService, CatalogueSpecialisation, PublicEvent
from app.schemas.content import ContentData
from app.services import catalogue, commercial, content, media

NOT_AVAILABLE = AppError(
    "PUBLIC_SERVICE_NOT_AVAILABLE", "This service is currently unavailable.", status.HTTP_404_NOT_FOUND
)


def _localized(lv: str, data: ContentData | None, pick: Any) -> dict[str, str]:
    result = {"lv": lv}
    if data is not None:
        for lang in ("en", "ru"):
            text = pick(data, lang)
            if text:
                result[lang] = text
    return result


def _image(item: Any, alt: dict[str, str] | None = None) -> dict[str, Any]:
    out = media.media_out(item)
    return {"urls": out.urls, "width": item.width, "height": item.height, "alt": alt or item.alt}


@dataclass
class _Cache:
    value: dict[str, Any] | None = None
    expires: float = 0.0


_cache = _Cache()
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.value, _cache.expires = None, 0.0


def _service_out(service: CatalogueService, data: ContentData | None) -> dict[str, Any]:
    texts = data.services.get(service.id, {}) if data else {}
    description = {k: v for k, v in texts.items() if v}
    return {
        "id": str(service.id),
        "w_id": service.w_id,
        "name": _localized(service.name, None, None),
        "description": description or None,
    }


def _spec_card(
    spec: CatalogueSpecialisation,
    services: list[CatalogueService],
    page: tuple[Any, ContentData | None] | None,
    images: dict[uuid.UUID, Any],
) -> dict[str, Any]:
    row, data = page if page else (None, None)
    name = _localized(
        spec.name, data, lambda d, lang: d.locales.get(lang).name if d.locales.get(lang) else None
    )
    card = None
    if data and data.card_image and data.card_image in images:
        card = _image(images[data.card_image])
    lead = None
    if data:
        lead = {lang: t.lead for lang, t in data.locales.items() if t.lead} or None
    return {
        "id": str(spec.id),
        # Without a content row the canonical Latvian slug is derived from the name (OQ-3).
        "slug": row.slug if row else content.slugify(spec.name),
        "name": name,
        "description": {"lv": spec.description} if spec.description else None,
        "lead": lead,
        "status": "active" if services else "planned",
        "services": [_service_out(s, data) for s in services],
        "card_image": card,
    }


def _build(db: Session) -> dict[str, Any]:
    categories = db.scalars(
        select(CatalogueCategory)
        .options(
            selectinload(CatalogueCategory.specialisations).selectinload(CatalogueSpecialisation.services)
        )
        # Planned categories hold only "Drīzumā" specialisations; nothing in them is orderable.
        .where(CatalogueCategory.status.in_(("active", "planned")))
        .order_by(CatalogueCategory.sort_order, CatalogueCategory.name)
    ).all()
    available = catalogue.availability(db)
    pages = content.published_data(db)
    image_ids = {d.card_image for _, d in pages.values() if d and d.card_image}
    images = media.publishable_ids(db, image_ids)
    out = []
    for category in categories:
        specs = []
        for spec in sorted(category.specialisations, key=lambda s: (s.sort_order, s.name)):
            services = sorted(
                (s for s in spec.services if available.get(s.id) and available[s.id].orderable),
                key=lambda s: (s.sort_order, s.name),
            )
            if category.status == "active" and spec.status == "active" and services:
                specs.append(_spec_card(spec, services, pages.get(spec.id), images))
            elif spec.status == "planned":
                specs.append(_spec_card(spec, [], pages.get(spec.id), images))
        if specs:
            out.append({"id": str(category.id), "name": {"lv": category.name}, "specialisations": specs})
    return {"computed_at": datetime.now(UTC).isoformat(), "categories": out}


def public_catalogue(db: Session) -> dict[str, Any]:
    """Cached for 60 s (OQ-2); availability is re-checked without cache when a request is
    created/submitted."""
    ttl = get_settings().public_cache_seconds
    with _lock:
        if _cache.value is not None and time.monotonic() < _cache.expires:
            return _cache.value
    value = _build(db)
    with _lock:
        _cache.value, _cache.expires = value, time.monotonic() + ttl
    return value


def orderable_service(db: Session, w_id: str) -> CatalogueService:
    service = db.scalar(
        select(CatalogueService)
        .options(selectinload(CatalogueService.specialisation).selectinload(CatalogueSpecialisation.category))
        .where(CatalogueService.w_id == w_id.upper())
    )
    if service is None:
        raise NOT_AVAILABLE
    if not catalogue.availability(db, [service.id])[service.id].orderable:
        raise NOT_AVAILABLE
    return service


def by_w_id(db: Session, w_id: str) -> dict[str, Any]:
    service = orderable_service(db, w_id)
    spec = service.specialisation
    page = content.published_data(db).get(spec.id)
    data = page[1] if page else None
    return {
        "service": _service_out(service, data),
        "specialisation": {
            "id": str(spec.id),
            "slug": page[0].slug if page else content.slugify(spec.name),
            "name": _localized(
                spec.name, data, lambda d, lang: d.locales.get(lang).name if d.locales.get(lang) else None
            ),
        },
        "category": {"id": str(spec.category.id), "name": {"lv": spec.category.name}},
    }


def specialisation_page(db: Session, slug_or_id: str) -> dict[str, Any] | str:
    """The page, or the new slug (str) when an old slug was requested."""
    spec_id: uuid.UUID | None = None
    try:
        spec_id = uuid.UUID(slug_or_id)
    except ValueError:
        row, moved = content.resolve_slug(db, slug_or_id)
        if moved:
            return moved
        if row is not None:
            spec_id = row.entity_id
        else:
            # A page without content yet: its address is the slug of the Latvian name.
            with_content = set(content.published_data(db))
            spec_id = next(
                (
                    sp.id
                    for sp in db.scalars(select(CatalogueSpecialisation))
                    if sp.id not in with_content and content.slugify(sp.name) == slug_or_id
                ),
                None,
            )
            if spec_id is None:
                raise AppError("NOT_FOUND", "Page not found.", status.HTTP_404_NOT_FOUND) from None
    spec = db.scalar(
        select(CatalogueSpecialisation)
        .options(
            selectinload(CatalogueSpecialisation.services), selectinload(CatalogueSpecialisation.category)
        )
        .where(CatalogueSpecialisation.id == spec_id)
    )
    if spec is None or spec.category.status != "active" or spec.status not in ("active", "planned"):
        raise AppError("NOT_FOUND", "Page not found.", status.HTTP_404_NOT_FOUND)
    available = catalogue.availability(db, [s.id for s in spec.services])
    services = sorted(
        (s for s in spec.services if spec.status == "active" and available[s.id].orderable),
        key=lambda s: (s.sort_order, s.name),
    )
    if spec.status == "active" and not services:
        raise AppError("NOT_FOUND", "Page not found.", status.HTTP_404_NOT_FOUND)
    page = content.published_data(db).get(spec.id)
    data = page[1] if page else None
    ids = (
        {g.media_id for g in data.gallery} | ({data.card_image} if data and data.card_image else set())
        if data
        else set()
    )
    images = media.publishable_ids(db, ids)
    card = _spec_card(spec, services, page, images)
    texts: dict[str, Any] = {}
    gallery: list[dict[str, Any]] = []
    if data:
        texts = {lang: t.model_dump(exclude_none=True) for lang, t in data.locales.items()}
        for item in data.gallery:
            if item.media_id in images:
                gallery.append({**_image(images[item.media_id]), "kind": item.kind, "caption": item.caption})
    terms = commercial.current(db)
    return {
        **card,
        "category": {"id": str(spec.category.id), "name": {"lv": spec.category.name}},
        "texts": texts,
        "gallery": gallery,
        "terms": {
            "hourly_rate_eur": str(terms.hourly_rate_eur),
            "minimum_order_eur": str(terms.minimum_order_eur),
            "materials_note": commercial.materials_note(terms).model_dump(exclude_none=True),
        },
    }


def record_public_event(
    db: Session, event_type: str, entity_id: uuid.UUID | None, source: str | None
) -> None:
    db.add(PublicEvent(event_type=event_type, entity_id=entity_id, source=source))
    db.commit()
