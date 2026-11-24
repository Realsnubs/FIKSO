"""Master work: availability, work city, languages, location (P1), offers and orders (D2–D3),
commission balance (P2).
Every route uses the caller's own master profile; other masters' orders return 404."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.api.v1.client import photo_response
from app.core.ratelimit import rate_limit
from app.models import MasterLocation, Order, ServiceRequest, User
from app.services import commission, master_availability, orders, places, settings, views

router = APIRouter(prefix="/master", tags=["master"])
MasterUser = Annotated[User, Depends(require_role("master"))]


def _work_profile(db: DbSession, user: User) -> dict[str, Any]:
    profile = master_availability.own_profile(db, user)
    location = db.get(MasterLocation, profile.id)
    summary = commission.summary(db, profile)
    return {
        "approval_status": profile.approval_status,
        "availability_mode": profile.availability_mode,
        "is_busy": profile.is_busy,
        "description": profile.description,
        # City-based work zone (2026-11-05): one primary city; no coordinates or radius.
        "work_city": places.master_city_code(db, profile.id),
        "languages": places.master_language_codes(db, profile.id),
        "location_updated_at": location.updated_at.isoformat() if location else None,
        "location_fresh": master_availability.location_fresh(db, location),
        "location_interval_seconds": 180,
        "rating_avg": str(profile.rating_avg) if profile.rating_avg is not None else None,
        "rating_count": profile.rating_count,
        "completed_jobs": profile.completed_jobs,
        "commission_balance_eur": str(summary.balance),
        "commission_limit_eur": str(summary.limit),
        "commission_limit_reached": summary.limit_reached,
    }


@router.get("/work-profile")
def get_work_profile(db: DbSession, user: MasterUser) -> dict[str, Any]:
    return _work_profile(db, user)


class ModeIn(BaseModel):
    mode: Literal["available_now", "available_for_reservations", "unavailable"]


@router.put("/availability")
def set_availability(db: DbSession, user: MasterUser, body: ModeIn) -> dict[str, Any]:
    master_availability.set_mode(db, user, body.mode)
    return _work_profile(db, user)


class CityIn(BaseModel):
    city: str = Field(min_length=2, max_length=40)


@router.put("/work-city")
def set_work_city(db: DbSession, user: MasterUser, body: CityIn) -> dict[str, Any]:
    master_availability.set_city(db, user, body.city)
    return _work_profile(db, user)


class LanguagesIn(BaseModel):
    languages: list[str] = Field(max_length=24)


@router.put("/languages")
def set_languages(db: DbSession, user: MasterUser, body: LanguagesIn) -> dict[str, Any]:
    master_availability.set_languages(db, user, body.languages)
    return _work_profile(db, user)


class DescriptionIn(BaseModel):
    description: str | None = Field(default=None, max_length=600)


@router.put("/profile-description")
def set_description(db: DbSession, user: MasterUser, body: DescriptionIn) -> dict[str, Any]:
    master_availability.set_description(db, user, body.description)
    return _work_profile(db, user)


class LocationIn(BaseModel):
    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0, le=100000)


@router.post(
    "/location",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("location", "rate_limit_location"))],
)
def post_location(db: DbSession, user: MasterUser, body: LocationIn) -> None:
    master_availability.update_location(
        db,
        user,
        body.lat.quantize(Decimal("0.000001")),
        body.lon.quantize(Decimal("0.000001")),
        body.accuracy_m,
    )


def _own_orders(db: DbSession, user: User, statuses: tuple[str, ...], limit: int = 50) -> list[Order]:
    profile = master_availability.own_profile(db, user)
    return list(
        db.scalars(
            select(Order)
            .where(Order.master_id == profile.id, Order.status.in_(statuses))
            .order_by(Order.created_at.desc())
            .limit(limit)
        ).all()
    )


@router.get("/offers")
def list_offers(db: DbSession, user: MasterUser) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    return [
        o
        for o in (views.master_order_out(db, x) for x in _own_orders(db, user, ("offered",)))
        if o["offer_expires_at"] and datetime.fromisoformat(o["offer_expires_at"]) > now
    ]


@router.get("/orders")
def list_orders(
    db: DbSession, user: MasterUser, scope: Literal["active", "history"] = "active"
) -> list[dict[str, Any]]:
    statuses = (
        ("accepted", "scheduled", "en_route", "in_progress")
        if scope == "active"
        else ("completed", "reviewed", "cancelled")
    )
    return [views.master_order_out(db, o) for o in _own_orders(db, user, statuses)]


@router.get("/orders/{order_id}")
def get_order(db: DbSession, user: MasterUser, order_id: uuid.UUID) -> dict[str, Any]:
    return views.master_order_out(db, orders.own_order(db, user, order_id))


@router.get("/orders/{order_id}/photos/{file_id}", response_class=Response)
def get_order_photo(
    db: DbSession, user: MasterUser, order_id: uuid.UUID, file_id: uuid.UUID
) -> StreamingResponse:
    order = orders.own_order(db, user, order_id)
    request = db.get(ServiceRequest, order.request_id)
    assert request is not None
    return photo_response(db, user, request, file_id)


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RequiredReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/orders/{order_id}/accept")
def accept(db: DbSession, user: MasterUser, order_id: uuid.UUID) -> dict[str, Any]:
    return views.master_order_out(db, orders.accept(db, user, order_id))


@router.post("/orders/{order_id}/decline")
def decline(db: DbSession, user: MasterUser, order_id: uuid.UUID, body: ReasonIn) -> dict[str, Any]:
    return views.master_order_out(db, orders.decline(db, user, order_id, body.reason))


@router.post("/orders/{order_id}/cancel")
def cancel(db: DbSession, user: MasterUser, order_id: uuid.UUID, body: RequiredReasonIn) -> dict[str, Any]:
    return views.master_order_out(db, orders.master_cancel(db, user, order_id, body.reason))


ACTIONS = {
    "depart": orders.depart,
    "arrive": orders.arrive,
    "start": orders.start_work,
    "pause": orders.pause,
    "resume": orders.resume,
    "finish": orders.finish_work,
    "finalise": orders.finalise,
}


@router.post("/orders/{order_id}/{action}")
def order_action(
    db: DbSession,
    user: MasterUser,
    order_id: uuid.UUID,
    action: Literal["depart", "arrive", "start", "pause", "resume", "finish", "finalise"],
) -> dict[str, Any]:
    return views.master_order_out(db, ACTIONS[action](db, user, order_id))


class MaterialIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, le=Decimal("100000"))
    unit: str | None = Field(default=None, max_length=20)
    amount_eur: Decimal = Field(ge=0, le=Decimal("100000"), decimal_places=2)


class WorksheetIn(BaseModel):
    work_description: str | None = Field(default=None, max_length=4000)
    limitations_explained: str | None = Field(default=None, max_length=2000)
    is_temporary_repair: bool = False
    internal_notes: str | None = Field(default=None, max_length=2000)
    materials: list[MaterialIn] = Field(default_factory=list, max_length=50)
    external_costs_eur: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000"), decimal_places=2)


@router.put("/orders/{order_id}/worksheet")
def save_worksheet(db: DbSession, user: MasterUser, order_id: uuid.UUID, body: WorksheetIn) -> dict[str, Any]:
    orders.update_worksheet(
        db,
        user,
        order_id,
        work_description=body.work_description,
        limitations=body.limitations_explained,
        temporary=body.is_temporary_repair,
        internal_notes=body.internal_notes,
        materials=[m.model_dump() for m in body.materials],
        external_costs=body.external_costs_eur,
    )
    return views.master_order_out(db, orders.own_order(db, user, order_id))


@router.get("/commission")
def get_commission(db: DbSession, user: MasterUser) -> dict[str, Any]:
    profile = master_availability.own_profile(db, user)
    summary = commission.summary(db, profile)
    return {
        "charged_total_eur": str(summary.charged_total),
        "paid_total_eur": str(summary.paid_total),
        "adjustments_total_eur": str(summary.adjustments_total),
        "balance_eur": str(summary.balance),
        "amount_due_eur": str(max(summary.balance, Decimal("0.00"))),
        "limit_eur": str(summary.limit),
        "limit_reached": summary.limit_reached,
        "entries": [
            {
                "id": str(e.id),
                "type": e.entry_type,
                "order_id": str(e.order_id) if e.order_id else None,
                "base_labour_eur": str(e.base_labour_eur) if e.base_labour_eur is not None else None,
                "rate": str(e.rate) if e.rate is not None else None,
                "amount_eur": str(e.amount_eur),
                "payment_method": e.payment_method,
                "paid_on": e.paid_on.isoformat() if e.paid_on else None,
                "comment": e.reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in commission.entries(db, profile.id)
        ],
    }


__all__ = ["settings", "timedelta"]
