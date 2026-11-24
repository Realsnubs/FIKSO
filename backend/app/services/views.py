"""Response builders that apply the privacy rules: the master sees the exact address and the client's phone
only once the order is assigned to them; the client sees no master contacts or exact location before that."""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Attachment,
    City,
    MasterLocation,
    MasterProfile,
    Order,
    OrderOffer,
    Review,
    ServiceRequest,
    User,
)
from app.schemas.requests import OrderSummary, PhotoOut, ProposalMaster, ProposalOut, RequestOut, ServiceRef
from app.services import matching, orders, places, requests

ASSIGNED = ("accepted", "scheduled", "en_route", "in_progress", "completed", "reviewed")


def _first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name.strip() else ""


def _photos(db: Session, request: ServiceRequest) -> list[PhotoOut]:
    return [
        PhotoOut(id=a.id, size_bytes=a.size_bytes, uploaded_at=a.uploaded_at)
        for a in requests.photos(db, request.id)
    ]


def _city(db: Session, code: str | None) -> dict[str, Any] | None:
    city = db.get(City, code) if code else None
    return places.city_out(city) if city else None


def _service(request: ServiceRequest) -> ServiceRef:
    snap = request.catalogue_snapshot
    return ServiceRef(
        id=request.service_id,
        w_id=snap["w_id"],
        name=snap["service_name"],
        specialisation=snap["specialisation_name"],
        category=snap["category_name"],
    )


def _approx(location: MasterLocation | None) -> dict[str, float] | None:
    # Approximate position only (≈ 1 km grid), and only while the master is on the way (privacy).
    if location is None:
        return None
    return {"lat": round(float(location.lat), 2), "lon": round(float(location.lon), 2)}


def _order_summary(db: Session, order: Order) -> OrderSummary:
    master, user = db.execute(
        select(MasterProfile, User)
        .join(User, User.id == MasterProfile.user_id)
        .where(MasterProfile.id == order.master_id)
    ).one()
    sheet = orders.worksheet(db, order)
    final = sheet is not None and sheet.state == "finalised"
    location = None
    if order.status == "en_route":
        location = _approx(db.get(MasterLocation, master.id))
    review = db.scalar(select(Review.rating).where(Review.order_id == order.id))
    return OrderSummary(
        id=order.id,
        status=order.status,
        master_name=_first_name(user.full_name),
        master_phone=user.phone if order.status in ASSIGNED else None,
        offered_at=order.offered_at,
        accepted_at=order.accepted_at,
        en_route_at=order.en_route_at,
        arrived_at=order.arrived_at,
        work_started_at=order.work_started_at,
        work_completed_at=order.work_completed_at,
        completed_at=order.completed_at,
        estimated_start=order.estimated_start,
        scheduled_start=order.scheduled_start,
        scheduled_end=order.scheduled_end,
        master_location=location,
        labour_amount_eur=sheet.labour_amount_eur if final and sheet else None,
        materials_amount_eur=sheet.materials_amount_eur if final and sheet else None,
        billable_minutes=(sheet.billable_seconds or 0) // 60 if final and sheet else None,
        work_description=sheet.work_description if final and sheet else None,
        review_rating=review,
    )


def request_out(db: Session, request: ServiceRequest) -> RequestOut:
    out = RequestOut(
        id=request.id,
        status=request.status,
        unserved_reason=request.unserved_reason,
        service=_service(request),
        description=request.description,
        request_type=request.request_type,
        preferred_time_from=request.preferred_time_from,
        preferred_time_to=request.preferred_time_to,
        address=request.address_formatted,
        flat=request.flat,
        access_info=request.access_info,
        geocode_source=request.geocode_source,
        city=_city(db, request.city_code),
        communication_language=request.communication_language or "any",
        source=request.source,
        current_round=request.current_round,
        photos=_photos(db, request),
        created_at=request.created_at,
        submitted_at=request.submitted_at,
        cancelled_at=request.cancelled_at,
        version=request.version,
    )
    found = matching.proposal(db, request)
    if found is not None:
        run, rows = found
        assert run.proposal_expires_at is not None
        out.proposal = ProposalOut(
            round=run.run_no,
            expires_at=run.proposal_expires_at,
            masters=[
                ProposalMaster(
                    candidate_id=c.id,
                    role=c.role_in_result,
                    first_name=_first_name(u.full_name),
                    description=m.description,
                    rating_avg=m.rating_avg,
                    rating_count=m.rating_count,
                    completed_jobs=m.completed_jobs,
                    eta_minutes=c.eta_minutes,
                    distance_km=c.distance_km,
                )
                for c, m, u in rows
            ],
        )
    order = db.scalar(
        select(Order).where(Order.request_id == request.id).order_by(Order.created_at.desc()).limit(1)
    )
    if order is not None and order.status not in ("declined", "expired"):
        out.order = _order_summary(db, order)
    return out


def master_order_out(db: Session, order: Order) -> dict[str, Any]:
    """An offer shows what is needed to judge the job; contacts and the exact address only after
    assignment."""
    request = db.get(ServiceRequest, order.request_id)
    assert request is not None
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id))
    client = db.get(User, order.client_id)
    assigned = order.status in ASSIGNED and order.status not in ("completed", "reviewed")
    sheet = orders.worksheet(db, order)
    data: dict[str, Any] = {
        "id": str(order.id),
        "status": order.status,
        "order_type": order.order_type,
        "service": _service(request).model_dump(mode="json"),
        "description": request.description,
        "photos": [p.model_dump(mode="json") for p in _photos(db, request)],
        "estimated_start": order.estimated_start.isoformat(),
        "scheduled_start": order.scheduled_start.isoformat() if order.scheduled_start else None,
        "scheduled_end": order.scheduled_end.isoformat() if order.scheduled_end else None,
        "offer_expires_at": offer.expires_at.isoformat() if offer else None,
        "city": _city(db, request.city_code),
        "communication_language": request.communication_language or "any",
        "client": None,
        "address": None,
        "timeline": {
            k: getattr(order, k).isoformat() if getattr(order, k) else None
            for k in (
                "offered_at",
                "accepted_at",
                "en_route_at",
                "arrived_at",
                "work_started_at",
                "work_completed_at",
                "completed_at",
            )
        },
        "work_running": False,
        "billable_seconds": orders.billable_seconds(db, order.id) if order.work_started_at else 0,
        "terms": {
            "hourly_rate_eur": str(order.hourly_rate_snapshot),
            "minimum_order_eur": str(order.minimum_order_snapshot),
            "commission_rate": str(order.commission_rate_snapshot),
        },
        "worksheet": None,
    }
    if assigned and client is not None:
        data["client"] = {"name": client.full_name, "phone": client.phone}
        data["address"] = {
            "address": request.address_formatted,
            "flat": request.flat,
            "access_info": request.access_info,
            "lat": float(request.lat),
            "lon": float(request.lon),
        }
    if order.status == "in_progress":
        from app.models import WorkSegment

        data["work_running"] = (
            db.scalar(
                select(WorkSegment.id).where(WorkSegment.order_id == order.id, WorkSegment.ended_at.is_(None))
            )
            is not None
        )
    if sheet is not None:
        from app.models import WorksheetMaterial

        materials = db.scalars(
            select(WorksheetMaterial).where(WorksheetMaterial.worksheet_id == sheet.id)
        ).all()
        data["worksheet"] = {
            "state": sheet.state,
            "work_description": sheet.work_description,
            "limitations_explained": sheet.limitations_explained,
            "is_temporary_repair": sheet.is_temporary_repair,
            "internal_notes": sheet.internal_notes,
            "materials": [
                {"name": m.name, "quantity": str(m.quantity), "unit": m.unit, "amount_eur": str(m.amount_eur)}
                for m in materials
            ],
            "materials_amount_eur": str(sheet.materials_amount_eur),
            "external_costs_eur": str(sheet.external_costs_eur),
            "billable_seconds": sheet.billable_seconds,
            "travel_minutes": sheet.travel_minutes,
            "labour_amount_eur": str(sheet.labour_amount_eur)
            if sheet.labour_amount_eur is not None
            else None,
            "commission_eur": str(sheet.commission_eur) if sheet.commission_eur is not None else None,
        }
    return data


def can_view_request_photo(db: Session, user: User, request: ServiceRequest) -> bool:
    if user.role == "admin" or request.client_id == user.id:
        return True
    if user.role != "master":
        return False
    return (
        db.scalar(
            select(Order.id)
            .join(MasterProfile, MasterProfile.id == Order.master_id)
            .where(
                Order.request_id == request.id,
                MasterProfile.user_id == user.id,
                Order.status.in_(("offered", *ASSIGNED)),
            )
        )
        is not None
    )


def attachment_of(db: Session, request: ServiceRequest, file_id: Any) -> Attachment | None:
    return db.scalar(
        select(Attachment).where(
            Attachment.id == file_id, Attachment.entity_type == "request", Attachment.entity_id == request.id
        )
    )


__all__ = ["Decimal"]
