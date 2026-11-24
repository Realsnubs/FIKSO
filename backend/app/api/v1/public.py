"""Public, unauthenticated catalogue API (C1, C2, C3, C6). Never exposes internal catalogue or master data."""

import hmac
import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.integrations.storage import KEY_PATTERN, get_public_storage
from app.schemas.commercial import PublicTermsOut
from app.schemas.public import Language
from app.services import commercial, media, notifications, places, public_catalogue

router = APIRouter(
    prefix="/public", tags=["public"], dependencies=[Depends(rate_limit("public", "rate_limit_public"))]
)
media_router = APIRouter(tags=["public"])
CACHE = {"Cache-Control": "public, max-age=60"}


@router.get("/catalogue")
def get_catalogue(db: DbSession, response: Response) -> dict[str, Any]:
    response.headers.update(CACHE)
    return public_catalogue.public_catalogue(db)


@router.get("/services/by-w-id/{w_id}")
def get_by_w_id(db: DbSession, w_id: Annotated[str, Path(pattern=r"^[Ww]\d{3,5}$")]) -> dict[str, Any]:
    return public_catalogue.by_w_id(db, w_id)


@router.get("/specialisations/{slug}", response_model=None)
def get_specialisation(
    db: DbSession, slug: Annotated[str, Path(max_length=80)], response: Response
) -> dict[str, Any] | RedirectResponse:
    page = public_catalogue.specialisation_page(db, slug)
    if isinstance(page, str):
        return RedirectResponse(f"/api/v1/public/specialisations/{page}", status.HTTP_308_PERMANENT_REDIRECT)
    response.headers.update(CACHE)
    return page


@router.get("/cities")
def get_cities(db: DbSession, response: Response) -> list[dict[str, Any]]:
    response.headers.update(CACHE)
    return [places.city_out(c) for c in places.cities(db)]


@router.get("/communication-languages")
def get_languages(db: DbSession, response: Response) -> list[dict[str, Any]]:
    """Languages a master can serve clients in — not the interface languages (LV/EN/RU)."""
    response.headers.update(CACHE)
    return [places.language_out(lang) for lang in places.languages(db)]


@router.get("/commercial-terms")
def get_terms(db: DbSession, lang: Language = "lv") -> PublicTermsOut:
    terms = commercial.current(db)
    note, note_lang = commercial.materials_note(terms).pick(lang)
    return PublicTermsOut(
        hourly_rate_eur=terms.hourly_rate_eur,
        minimum_order_eur=terms.minimum_order_eur,
        materials_note=note,
        materials_note_lang=note_lang,
    )


class PublicEventIn(BaseModel):
    event_type: Literal["catalogue_view", "specialisation_view", "service_selected"]
    entity_id: uuid.UUID | None = None
    source: Literal["web", "app"] | None = None
    note: str | None = Field(default=None, max_length=0)


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
def post_event(db: DbSession, body: PublicEventIn) -> None:
    public_catalogue.record_public_event(db, body.event_type, body.entity_id, body.source)


@media_router.get("/media/{key}", response_class=Response)
def get_media(db: DbSession, key: Annotated[str, Path(max_length=32)]) -> StreamingResponse:
    """Processed public variants only; an archived image or one whose consent was withdrawn is never
    served."""
    if not KEY_PATTERN.match(key) or not re.fullmatch(r"[0-9a-f]{32}", key):
        raise AppError("NOT_FOUND", "Not found.", status.HTTP_404_NOT_FOUND)
    if media.publishable_by_key(db, key) is None:
        raise AppError("NOT_FOUND", "Not found.", status.HTTP_404_NOT_FOUND)
    try:
        handle = get_public_storage().open(key)
    except FileNotFoundError as exc:
        raise AppError("NOT_FOUND", "Not found.", status.HTTP_404_NOT_FOUND) from exc
    return StreamingResponse(
        handle,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/sms/messente", status_code=status.HTTP_204_NO_CONTENT)
async def messente_delivery_report(request: Request, db: DbSession, token: str = "") -> None:
    """Delivery report (DLR) from Messente. Authenticated by the shared secret in the URL; compared in
    constant
    time. Unknown message IDs are ignored, so a repeated report is harmless."""
    expected = get_settings().sms_webhook_token
    if expected is None or not hmac.compare_digest(token, expected.get_secret_value()):
        raise AppError("FORBIDDEN", "Invalid token.", status.HTTP_403_FORBIDDEN)
    try:
        body = await request.json()
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", "Invalid body.", status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    message_id, provider_status = body.get("message_id"), body.get("status")
    if isinstance(message_id, str) and isinstance(provider_status, str):
        notifications.record_delivery(db, message_id, provider_status.upper())
