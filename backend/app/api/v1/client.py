"""Client requests and orders (D1–D3). Every route works only on the caller's own records; others are 404."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.integrations.storage import get_storage
from app.models import Order, ServiceRequest, User
from app.schemas.requests import (
    CancelIn,
    PhotoOut,
    RequestCreateIn,
    RequestListItem,
    RequestOut,
    RequestUpdateIn,
)
from app.services import notifications, orders, public_catalogue, requests, views

router = APIRouter(prefix="/client", tags=["client"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
ClientUser = Annotated[User, Depends(require_role("client"))]


@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("requests", "rate_limit_requests"))],
)
def create_request(
    db: DbSession,
    user: ClientUser,
    body: RequestCreateIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)] = None,
) -> RequestOut:
    request = requests.create(db, user, body, idempotency_key)
    public_catalogue.record_public_event(
        db, "service_selected", request.service_id, "web" if request.source == "website_deeplink" else "app"
    )
    return views.request_out(db, request)


@router.get("/requests")
def list_requests(db: DbSession, user: ClientUser) -> list[RequestListItem]:
    rows = db.scalars(
        select(ServiceRequest)
        .where(ServiceRequest.client_id == user.id)
        .order_by(ServiceRequest.created_at.desc())
        .limit(100)
    ).all()
    latest: dict[uuid.UUID, str] = {}
    for order in db.scalars(select(Order).where(Order.client_id == user.id).order_by(Order.created_at)):
        latest[order.request_id] = order.status
    return [
        RequestListItem(
            id=r.id,
            status=r.status,
            w_id=r.catalogue_snapshot["w_id"],
            service_name=r.catalogue_snapshot["service_name"],
            created_at=r.created_at,
            order_status=latest.get(r.id),
        )
        for r in rows
    ]


@router.get("/requests/{request_id}")
def get_request(db: DbSession, user: ClientUser, request_id: uuid.UUID) -> RequestOut:
    return views.request_out(db, requests.get_own(db, user, request_id))


@router.patch("/requests/{request_id}")
def update_request(
    db: DbSession, user: ClientUser, request_id: uuid.UUID, body: RequestUpdateIn
) -> RequestOut:
    return views.request_out(db, requests.update(db, user, request_id, body))


@router.post(
    "/requests/{request_id}/photos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload"))],
)
def add_photo(
    db: DbSession, user: ClientUser, request_id: uuid.UUID, file: Annotated[UploadFile, File()]
) -> PhotoOut:
    row = requests.add_photo(db, get_storage(), user, request_id, file)
    return PhotoOut(id=row.id, size_bytes=row.size_bytes, uploaded_at=row.uploaded_at)


@router.delete("/requests/{request_id}/photos/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(db: DbSession, user: ClientUser, request_id: uuid.UUID, file_id: uuid.UUID) -> None:
    requests.delete_photo(db, get_storage(), user, request_id, file_id)


def photo_response(
    db: DbSession, user: User, request: ServiceRequest, file_id: uuid.UUID
) -> StreamingResponse:
    if not views.can_view_request_photo(db, user, request):
        raise AppError("NOT_FOUND", "Photo not found.", status.HTTP_404_NOT_FOUND)
    attachment = views.attachment_of(db, request, file_id)
    if attachment is None:
        raise AppError("NOT_FOUND", "Photo not found.", status.HTTP_404_NOT_FOUND)
    try:
        handle = get_storage().open(attachment.storage_key)
    except FileNotFoundError as exc:
        raise AppError("FILE_UNAVAILABLE", "The file is not available.", status.HTTP_404_NOT_FOUND) from exc
    requests.log_photo_view(db, user, attachment)
    return StreamingResponse(
        handle,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'inline; filename="{attachment.id}.jpg"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store, private",
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'",
        },
    )


@router.get("/requests/{request_id}/photos/{file_id}", response_class=Response)
def get_photo(
    db: DbSession, user: ClientUser, request_id: uuid.UUID, file_id: uuid.UUID
) -> StreamingResponse:
    return photo_response(db, user, requests.get_own(db, user, request_id), file_id)


@router.post("/requests/{request_id}/submit")
def submit(db: DbSession, user: ClientUser, request_id: uuid.UUID) -> RequestOut:
    return views.request_out(db, requests.submit(db, user, request_id))


@router.post("/requests/{request_id}/cancel")
def cancel(db: DbSession, user: ClientUser, request_id: uuid.UUID, body: CancelIn) -> RequestOut:
    return views.request_out(db, requests.cancel(db, user, request_id, body.reason))


class ConfirmIn(BaseModel):
    candidate_id: uuid.UUID


@router.post("/requests/{request_id}/confirm")
def confirm(db: DbSession, user: ClientUser, request_id: uuid.UUID, body: ConfirmIn) -> RequestOut:
    orders.confirm(db, user, request_id, body.candidate_id)
    return views.request_out(db, requests.get_own(db, user, request_id))


@router.post("/requests/{request_id}/reject")
def reject(db: DbSession, user: ClientUser, request_id: uuid.UUID) -> RequestOut:
    return views.request_out(db, orders.reject_proposal(db, user, request_id))


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/orders/{order_id}/review", status_code=status.HTTP_201_CREATED)
def review(db: DbSession, user: ClientUser, order_id: uuid.UUID, body: ReviewIn) -> dict[str, Any]:
    row = orders.review(db, user, order_id, body.rating, body.comment)
    return {"id": str(row.id), "rating": row.rating}


class ReadIn(BaseModel):
    ids: list[uuid.UUID] | None = None


@notifications_router.get("")
def list_notifications(db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    return [
        {
            "id": str(n.id),
            "type": n.type,
            "payload": n.payload,
            "created_at": n.created_at.isoformat(),
            "read": n.read_at is not None,
        }
        for n in notifications.list_for(db, user)
    ]


@notifications_router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
def read_notifications(db: DbSession, user: CurrentUser, body: ReadIn) -> None:
    notifications.mark_read(db, user, body.ids)
