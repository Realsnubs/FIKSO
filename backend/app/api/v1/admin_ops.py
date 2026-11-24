"""Admin: commission balances and payments (P2), request/order monitoring (D2–D3), statistics (C7),
operational settings and worker status. Admin role only; every write is audited."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.core.errors import AppError
from app.models import (
    JobRun,
    MasterProfile,
    MatchingCandidate,
    MatchingRun,
    Order,
    OrderStatusHistory,
    ServiceRequest,
    SystemSetting,
    User,
)
from app.services import billable, commission, orders, settings, stats, views
from app.services.events import record_audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/commission/masters")
def commission_masters(db: DbSession, _: AdminUser) -> list[dict[str, Any]]:
    return [
        {
            "master_id": str(m.id),
            "name": u.full_name,
            "email": u.email,
            "balance_eur": str(b),
            "limit_eur": str(m.commission_limit_eur),
            "limit_reached": b >= m.commission_limit_eur,
        }
        for m, u, b in commission.overview(db)
    ]


@router.get("/commission/masters/{master_id}")
def commission_master(db: DbSession, _: AdminUser, master_id: uuid.UUID) -> dict[str, Any]:
    master = db.get(MasterProfile, master_id)
    if master is None:
        raise AppError("NOT_FOUND", "Master not found.", 404)
    user = db.get(User, master.user_id)
    summary = commission.summary(db, master)
    return {
        "master_id": str(master.id),
        "name": user.full_name if user else "",
        "charged_total_eur": str(summary.charged_total),
        "paid_total_eur": str(summary.paid_total),
        "adjustments_total_eur": str(summary.adjustments_total),
        "balance_eur": str(summary.balance),
        "limit_eur": str(summary.limit),
        "limit_reached": summary.limit_reached,
        "entries": [
            {
                "id": str(e.id),
                "type": e.entry_type,
                "order_id": str(e.order_id) if e.order_id else None,
                "amount_eur": str(e.amount_eur),
                "base_labour_eur": str(e.base_labour_eur) if e.base_labour_eur is not None else None,
                "payment_method": e.payment_method,
                "paid_on": e.paid_on.isoformat() if e.paid_on else None,
                "reference": e.reference,
                "comment": e.reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in commission.entries(db, master.id)
        ],
    }


class PaymentIn(BaseModel):
    amount_eur: Decimal = Field(gt=0, le=Decimal("100000"), decimal_places=2)
    paid_on: date
    payment_method: Literal["cash", "bank_transfer"]
    reference: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=500)


@router.post("/commission/masters/{master_id}/payments", status_code=201)
def record_payment(
    db: DbSession,
    admin: AdminUser,
    master_id: uuid.UUID,
    body: PaymentIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)] = None,
) -> dict[str, Any]:
    commission.record_payment(
        db,
        admin,
        master_id,
        body.amount_eur,
        body.paid_on,
        body.payment_method,
        body.reference,
        body.comment,
        idempotency_key,
    )
    return commission_master(db, admin, master_id)


class AdjustmentIn(BaseModel):
    amount_eur: Decimal = Field(ge=Decimal("-100000"), le=Decimal("100000"), decimal_places=2)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/commission/masters/{master_id}/adjustments", status_code=201)
def record_adjustment(
    db: DbSession,
    admin: AdminUser,
    master_id: uuid.UUID,
    body: AdjustmentIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=80)] = None,
) -> dict[str, Any]:
    if body.amount_eur == 0:
        raise AppError("VALIDATION_ERROR", "An adjustment cannot be zero.", 422)
    commission.record_adjustment(db, admin, master_id, body.amount_eur, body.reason, idempotency_key)
    return commission_master(db, admin, master_id)


class LimitIn(BaseModel):
    new_limit_eur: Decimal = Field(ge=0, le=Decimal("100000"), decimal_places=2)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/commission/masters/{master_id}/limit")
def change_limit(db: DbSession, admin: AdminUser, master_id: uuid.UUID, body: LimitIn) -> dict[str, Any]:
    commission.change_limit(db, admin, master_id, body.new_limit_eur, body.reason)
    return commission_master(db, admin, master_id)


@router.get("/requests")
def list_requests(
    db: DbSession, _: AdminUser, status: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict[str, Any]]:
    query = select(ServiceRequest).order_by(ServiceRequest.created_at.desc()).limit(limit)
    if status:
        query = query.where(ServiceRequest.status == status)
    out = []
    for r in db.scalars(query):
        order = db.scalar(
            select(Order).where(Order.request_id == r.id).order_by(Order.created_at.desc()).limit(1)
        )
        out.append(
            {
                "id": str(r.id),
                "status": r.status,
                "w_id": r.catalogue_snapshot["w_id"],
                "service_name": r.catalogue_snapshot["service_name"],
                "request_type": r.request_type,
                "source": r.source,
                "round": r.current_round,
                "created_at": r.created_at.isoformat(),
                "order_status": order.status if order else None,
                "unserved_reason": r.unserved_reason,
                "city": r.city_code,
                "communication_language": r.communication_language or "any",
            }
        )
    return out


@router.get("/requests/{request_id}")
def get_request(db: DbSession, _: AdminUser, request_id: uuid.UUID) -> dict[str, Any]:
    request = db.get(ServiceRequest, request_id)
    if request is None:
        raise AppError("NOT_FOUND", "Request not found.", 404)
    out = views.request_out(db, request).model_dump(mode="json")
    runs = []
    for run in db.scalars(
        select(MatchingRun).where(MatchingRun.request_id == request.id).order_by(MatchingRun.created_at)
    ):
        cands = db.execute(
            select(MatchingCandidate, User.full_name)
            .join(MasterProfile, MasterProfile.id == MatchingCandidate.master_id)
            .join(User, User.id == MasterProfile.user_id)
            .where(MatchingCandidate.matching_run_id == run.id)
            .order_by(MatchingCandidate.rank)
        ).all()
        runs.append(
            {
                "run_no": run.run_no,
                "attempt": run.attempt,
                "outcome": run.outcome,
                "eligible": run.eligible_count,
                "available": run.available_count,
                "excluded": run.excluded_counts,
                "close_reason": run.close_reason,
                "created_at": run.created_at.isoformat(),
                "closed_at": run.closed_at.isoformat() if run.closed_at else None,
                "candidates": [
                    {
                        "rank": c.rank,
                        "master": name,
                        "eta_minutes": c.eta_minutes,
                        "eta_source": c.eta_source,
                        "distance_km": str(c.distance_km),
                        "role": c.role_in_result,
                        "chosen": c.chosen_by_client,
                    }
                    for c, name in cands
                ],
            }
        )
    history = db.scalars(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.request_id == request.id)
        .order_by(OrderStatusHistory.created_at)
    ).all()
    out["rounds"] = runs
    out["history"] = [
        {
            "entity": h.entity,
            "from": h.from_status,
            "to": h.to_status,
            "actor_type": h.actor_type,
            "reason": h.reason,
            "at": h.created_at.isoformat(),
        }
        for h in history
    ]
    out["address"] = request.address_formatted
    return out


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/requests/{request_id}/cancel")
def cancel_request(db: DbSession, admin: AdminUser, request_id: uuid.UUID, body: CancelIn) -> dict[str, Any]:
    orders.admin_cancel(db, admin, request_id, body.reason)
    return get_request(db, admin, request_id)


@router.get("/masters/{master_id}/work")
def master_work(db: DbSession, _: AdminUser, master_id: uuid.UUID) -> dict[str, Any]:
    """City, communication languages and availability of a master (read-only for the admin)."""
    master = db.get(MasterProfile, master_id)
    if master is None:
        raise AppError("NOT_FOUND", "Master not found.", 404)
    from app.models import City, MasterLocation
    from app.services import master_availability, places

    code = places.master_city_code(db, master.id)
    city = db.get(City, code) if code else None
    location = db.get(MasterLocation, master.id)
    return {
        "work_city": places.city_out(city) if city else None,
        "languages": places.master_language_codes(db, master.id),
        "availability_mode": master.availability_mode,
        "is_busy": master.is_busy,
        "location_fresh": master_availability.location_fresh(db, location),
        "ready_for_matching": bool(city) and bool(places.master_language_codes(db, master.id)),
    }


@router.get("/stats/overview")
def stats_overview(
    db: DbSession, _: AdminUser, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> dict[str, Any]:
    return stats.overview(db, days)


@router.get("/settings")
def get_settings(db: DbSession, _: AdminUser) -> dict[str, Any]:
    return {
        **settings.all_settings(db),
        "unconfirmed_policies": settings.unconfirmed_policies(db),
        "billable_options": billable.OPTIONS,
    }


EDITABLE: dict[str, tuple[int, int]] = {"immediate_job_minutes": (15, 720), "order_buffer_minutes": (0, 240)}


class SettingIn(BaseModel):
    value: int
    reason: str = Field(min_length=3, max_length=500)


def _save(db: DbSession, admin: User, key: str, value: Any, reason: str) -> None:
    row = db.get(SystemSetting, key)
    before = row.value if row else None
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=admin.id))
    else:
        row.value, row.updated_by = value, admin.id
    record_audit(
        db,
        "settings.changed",
        "system_setting",
        None,
        "user",
        admin.id,
        before={key: before},
        after={key: value},
        reason=reason,
    )
    db.commit()


@router.put("/settings/{key}")
def put_setting(db: DbSession, admin: AdminUser, key: str, body: SettingIn) -> dict[str, Any]:
    """Only the open working assumptions (Q-D2-1) are editable here; owner-decided timeouts are not."""
    if key not in EDITABLE:
        raise AppError("NOT_EDITABLE", "This setting cannot be changed here.", 422)
    low, high = EDITABLE[key]
    if not low <= body.value <= high:
        raise AppError("VALIDATION_ERROR", f"Allowed range {low}–{high}.", 422)
    _save(db, admin, key, body.value, body.reason)
    return get_settings(db, admin)


class BillableRuleIn(BaseModel):
    rounding: Literal["none", "up", "nearest", "down"]
    step_minutes: int = Field(ge=1, le=60)
    reason: str = Field(min_length=3, max_length=500)


@router.put("/settings/billable-time/rule")
def put_billable_rule(db: DbSession, admin: AdminUser, body: BillableRuleIn) -> dict[str, Any]:
    """Changing the rule also withdraws its approval: a new rule is unapproved until the owner confirms it."""
    _save(
        db,
        admin,
        "billable_time",
        {"rounding": body.rounding, "step_minutes": body.step_minutes},
        body.reason,
    )
    confirmation = dict(settings.get(db, "policy_confirmation"), billable_time=False)
    _save(db, admin, "policy_confirmation", confirmation, "rule changed: approval withdrawn")
    return get_settings(db, admin)


class ConfirmIn(BaseModel):
    policy: Literal["billable_time", "immediate_job_minutes", "order_buffer_minutes"]
    confirmed: bool
    reason: str = Field(min_length=3, max_length=500)


@router.post("/settings/policy-confirmation")
def confirm_policy(db: DbSession, admin: AdminUser, body: ConfirmIn) -> dict[str, Any]:
    """Records that the owner approved (or withdrew approval of) a working assumption; audited with reason."""
    confirmation = dict(settings.get(db, "policy_confirmation"), **{body.policy: body.confirmed})
    _save(db, admin, "policy_confirmation", confirmation, body.reason)
    return get_settings(db, admin)


@router.get("/jobs")
def recent_jobs(db: DbSession, _: AdminUser) -> list[dict[str, Any]]:
    rows = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(40)).all()
    return [
        {
            "job": r.job_name,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "items": r.items_processed,
            "error": r.error,
        }
        for r in rows
    ]
