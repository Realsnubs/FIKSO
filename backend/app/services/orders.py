"""Order state machine (ARCHITECTURE §5, D2–D3). Every transition runs in one transaction with its history row
and domain event. Lock order everywhere: request → order → master.

Option A (owner decision Q-FINAL-01): the client confirms the shown master, and only then an `orders` row is
created in `offered`. That row is the master's time block; accepting moves the same row to `accepted`, so the
block has no gap. The GiST exclusion constraint rejects any overlapping blocking row of the same master.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    CommercialTerms,
    MasterProfile,
    MatchingCandidate,
    MatchingRun,
    Order,
    OrderDeparture,
    OrderOffer,
    Review,
    ServiceRequest,
    User,
    WorkSegment,
    Worksheet,
    WorksheetMaterial,
)
from app.services import billable, commercial, commission, matching, settings
from app.services.events import record_audit, record_event
from app.services.lifecycle import order_status, request_status
from app.services.money import commission as commission_amount
from app.services.money import eur, labour_amount
from app.services.notifications import notify

LIVE = ("offered", "accepted", "scheduled", "en_route", "in_progress")
MASTER_CANCELLABLE = ("accepted", "scheduled", "en_route")
ENDED_UNSUCCESSFULLY = ("declined", "expired", "cancelled")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def conflict(code: str, message: str) -> AppError:
    return AppError(code, message, status.HTTP_409_CONFLICT)


def live_order(db: Session, request_id: uuid.UUID, lock: bool = False) -> Order | None:
    query = select(Order).where(Order.request_id == request_id, Order.status.in_(LIVE))
    return db.scalar(query.with_for_update() if lock else query)


def has_order(db: Session, request_id: uuid.UUID) -> bool:
    """A live or finished order exists (anything but declined/expired/cancelled)."""
    query = select(Order.id).where(Order.request_id == request_id, Order.status.not_in(ENDED_UNSUCCESSFULLY))
    return db.scalar(query.limit(1)) is not None


def _lock_request(db: Session, request_id: uuid.UUID) -> ServiceRequest:
    request = db.scalar(select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise AppError("NOT_FOUND", "Request not found.", status.HTTP_404_NOT_FOUND)
    return request


def _lock_master(db: Session, master_id: uuid.UUID) -> MasterProfile:
    master = db.scalar(select(MasterProfile).where(MasterProfile.id == master_id).with_for_update())
    assert master is not None
    return master


def _offer(db: Session, order: Order) -> OrderOffer:
    offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id))
    assert offer is not None
    return offer


def _run(db: Session, order: Order) -> MatchingRun:
    run = db.get(MatchingRun, order.matching_run_id)
    assert run is not None
    return run


# ---------------------------------------------------------------- client: confirm / reject the proposal


def confirm(
    db: Session, user: User, request_id: uuid.UUID, candidate_id: uuid.UUID, now: datetime | None = None
) -> Order:
    """Client confirms one shown master. Re-checks every condition under the master lock, then creates the
    order (`offered`) and its offer atomically; the master's interval is blocked from here on."""
    now = _now(now)
    request = _lock_request(db, request_id)
    if request.client_id != user.id:
        raise AppError("NOT_FOUND", "Request not found.", status.HTTP_404_NOT_FOUND)
    run = matching.open_run(db, request)
    if request.status != "proposed" or run is None or run.outcome != "proposed":
        raise conflict("NO_OPEN_PROPOSAL", "There is no proposal to confirm.")
    if run.proposal_expires_at is None or run.proposal_expires_at <= now:
        raise conflict("PROPOSAL_EXPIRED", "The time to confirm has passed. A new proposal will follow.")
    candidate = db.scalar(
        select(MatchingCandidate).where(
            MatchingCandidate.id == candidate_id,
            MatchingCandidate.matching_run_id == run.id,
            MatchingCandidate.role_in_result != "not_shown",
        )
    )
    if candidate is None:
        raise AppError("NOT_FOUND", "Master not in this proposal.", status.HTTP_404_NOT_FOUND)
    _lock_master(db, candidate.master_id)
    still, _, _ = matching.candidates(db, request, now, only_master=candidate.master_id)
    if not still:
        return _technical_retry(db, request, run, now)
    eta = still[0].eta_minutes
    busy_range, est_start, est_end = matching.block_range(db, request, eta, now)
    terms = (
        db.get(CommercialTerms, request.commercial_terms_id)
        if request.commercial_terms_id
        else commercial.current(db)
    )
    assert terms is not None
    response_minutes = int(settings.get(db, "master_response_minutes")[request.request_type])
    order = Order(
        request_id=request.id,
        matching_run_id=run.id,
        client_id=request.client_id,
        master_id=candidate.master_id,
        order_type=request.request_type,
        status="offered",
        estimated_start=est_start,
        estimated_end=est_end,
        busy_range=busy_range,
        client_confirmed_at=now,
        offered_at=now,
        scheduled_start=request.preferred_time_from,
        scheduled_end=request.preferred_time_to,
        commission_rate_snapshot=commission.current_settings(db).rate,
        communication_language=request.communication_language,
        hourly_rate_snapshot=terms.hourly_rate_eur,
        minimum_order_snapshot=terms.minimum_order_eur,
    )
    try:
        with db.begin_nested():
            db.add(order)
            db.flush()
            db.add(
                OrderOffer(
                    order_id=order.id,
                    master_id=order.master_id,
                    offered_at=now,
                    expires_at=now + timedelta(minutes=response_minutes),
                )
            )
            db.flush()
    except IntegrityError:
        # The exclusion constraint saw an overlapping assignment that the re-check could not (defence in
        # depth).
        return _technical_retry(db, request, run, now)
    candidate.chosen_by_client = True
    matching.close_run(run, "client_confirmed", now)
    order_status(db, order, "offered", "user", user.id)
    request_status(db, request, "confirmed", "user", user.id)
    master_user = db.scalar(select(MasterProfile.user_id).where(MasterProfile.id == order.master_id))
    assert master_user is not None
    notify(db, master_user, "offer.new", {"order_id": str(order.id)})
    db.commit()
    return order


def _technical_retry(db: Session, request: ServiceRequest, run: MatchingRun, now: datetime) -> Order:
    """The chosen master became unavailable: a fresh run in the same round, not a new round (Q-FINAL-03)."""
    matching.close_run(run, "conflict", now)
    request_status(db, request, "matching", "system", None, reason="master_no_longer_available")
    matching.start_round(db, request, now, retry=True)
    db.commit()
    raise conflict(
        "MASTER_NO_LONGER_AVAILABLE", "This master is no longer available. A new proposal is ready."
    )


def reject_proposal(
    db: Session, user: User, request_id: uuid.UUID, now: datetime | None = None
) -> ServiceRequest:
    now = _now(now)
    request = _lock_request(db, request_id)
    if request.client_id != user.id:
        raise AppError("NOT_FOUND", "Request not found.", status.HTTP_404_NOT_FOUND)
    run = matching.open_run(db, request)
    if request.status != "proposed" or run is None:
        raise conflict("NO_OPEN_PROPOSAL", "There is no proposal to reject.")
    matching.close_run(run, "client_rejected", now)
    matching.next_round(db, request, now)
    db.commit()
    return request


def expire_proposal(db: Session, run_id: uuid.UUID, now: datetime | None = None) -> bool:
    """Worker: the client did not confirm in time — the round ends; the shown master is not excluded."""
    now = _now(now)
    run = db.get(MatchingRun, run_id)
    if run is None:
        return False
    request = _lock_request(db, run.request_id)
    db.refresh(run, with_for_update=True)
    if (
        run.closed_at is not None
        or request.status != "proposed"
        or not run.proposal_expires_at
        or run.proposal_expires_at > now
    ):
        return False
    matching.close_run(run, "client_timeout", now)
    record_event(
        db, "proposal.expired", "service_request", request.id, "system", None, {"run_no": run.run_no}
    )
    matching.next_round(db, request, now)
    db.commit()
    return True


# ---------------------------------------------------------------- master: accept / decline / expiry


def own_order(db: Session, user: User, order_id: uuid.UUID, lock: bool = False) -> Order:
    query = (
        select(Order)
        .join(MasterProfile, MasterProfile.id == Order.master_id)
        .where(Order.id == order_id, MasterProfile.user_id == user.id)
    )
    order = db.scalar(query.with_for_update(of=Order) if lock else query)
    if order is None:
        raise AppError("NOT_FOUND", "Order not found.", status.HTTP_404_NOT_FOUND)
    return order


def accept(db: Session, user: User, order_id: uuid.UUID, now: datetime | None = None) -> Order:
    """The same row moves offered → accepted/scheduled; the time block continues without a gap.

    An already issued offer stays valid if the master reached the commission limit meanwhile (Q-D2-2).
    """
    now = _now(now)
    order = own_order(db, user, order_id)
    request = _lock_request(db, order.request_id)
    db.refresh(order, with_for_update=True)
    if order.status != "offered":
        raise conflict("OFFER_NOT_OPEN", "This offer is no longer open.")
    offer = _offer(db, order)
    if offer.expires_at <= now:
        raise conflict("OFFER_EXPIRED", "The time to answer has passed.")
    _lock_master(db, order.master_id)
    offer.response, offer.responded_at = "accepted", now
    order.accepted_at = now
    order_status(db, order, "scheduled" if order.order_type == "reserved" else "accepted", "user", user.id)
    matching.close_run(_run(db, order), "master_accepted", now)
    notify(db, request.client_id, "order.accepted", {"order_id": str(order.id)})
    db.commit()
    return order


def decline(
    db: Session, user: User, order_id: uuid.UUID, reason: str | None, now: datetime | None = None
) -> Order:
    """Explicit decline: block released, master excluded for this request, next round (Q-FINAL-03)."""
    now = _now(now)
    order = own_order(db, user, order_id)
    request = _lock_request(db, order.request_id)
    db.refresh(order, with_for_update=True)
    if order.status != "offered":
        raise conflict("OFFER_NOT_OPEN", "This offer is no longer open.")
    offer = _offer(db, order)
    offer.response, offer.responded_at = "declined", now
    order_status(db, order, "declined", "user", user.id, reason)
    matching.close_run(_run(db, order), "master_declined", now)
    matching.next_round(db, request, now)
    db.commit()
    return order


def expire_offer(db: Session, order_id: uuid.UUID, now: datetime | None = None) -> bool:
    """Worker: the master did not answer — block released, master NOT excluded, next round."""
    now = _now(now)
    order = db.get(Order, order_id)
    if order is None:
        return False
    request = _lock_request(db, order.request_id)
    db.refresh(order, with_for_update=True)
    offer = _offer(db, order)
    if order.status != "offered" or offer.expires_at > now:
        return False
    offer.response, offer.responded_at = "expired", now
    order_status(db, order, "expired", "system", None)
    matching.close_run(_run(db, order), "master_expired", now)
    record_event(db, "offer.expired", "order", order.id, "system", None)
    if request.status == "confirmed":
        matching.next_round(db, request, now)
    db.commit()
    return True


def cancel_for_request(
    db: Session, request: ServiceRequest, role: str, actor_id: uuid.UUID | None, reason: str | None
) -> None:
    """Cancel a request and its live order before work starts; the master's interval is released at once."""
    now = datetime.now(UTC)
    order = live_order(db, request.id, lock=True)
    if order is not None:
        if order.status == "in_progress":
            raise conflict("CANNOT_CANCEL", "Work has already started.")
        offer = _offer(db, order)
        if offer.response is None:
            offer.response, offer.responded_at = "cancelled", now
        order.cancelled_at, order.cancel_reason, order.cancelled_by_role = now, reason, role
        order_status(db, order, "cancelled", "user", actor_id, reason)
        master_user = db.scalar(select(MasterProfile.user_id).where(MasterProfile.id == order.master_id))
        if master_user:
            notify(db, master_user, "order.cancelled", {"order_id": str(order.id)})
    run = matching.open_run(db, request)
    if run is not None:
        matching.close_run(run, "cancelled", now)
    request.cancelled_at, request.cancel_reason = now, reason
    request_status(db, request, "cancelled", "user", actor_id, reason)


def master_cancel(db: Session, user: User, order_id: uuid.UUID, reason: str) -> Order:
    """A master who can no longer do an accepted job: released, treated like a decline, next round."""
    now = datetime.now(UTC)
    order = own_order(db, user, order_id)
    request = _lock_request(db, order.request_id)
    db.refresh(order, with_for_update=True)
    if order.status not in MASTER_CANCELLABLE:
        raise conflict("CANNOT_CANCEL", "This order can no longer be cancelled.")
    offer = _offer(db, order)
    offer.response = "declined"
    order.cancelled_at, order.cancel_reason, order.cancelled_by_role = now, reason, "master"
    order_status(db, order, "cancelled", "user", user.id, reason)
    notify(db, request.client_id, "order.cancelled_by_master", {"order_id": str(order.id)})
    if request.status == "confirmed":
        matching.next_round(db, request, now)
    db.commit()
    return order


# ---------------------------------------------------------------- D3: departure, arrival, work, work sheet


def _transition(db: Session, user: User, order_id: uuid.UUID, allowed: tuple[str, ...]) -> Order:
    order = own_order(db, user, order_id, lock=True)
    if order.status not in allowed:
        raise conflict("INVALID_TRANSITION", f"Not possible while the order is {order.status}.")
    return order


def depart(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("accepted", "scheduled"))
    now = datetime.now(UTC)
    order.en_route_at = now
    history = order_status(db, order, "en_route", "user", user.id)
    db.flush()
    db.add(
        OrderDeparture(
            order_id=order.id, master_id=order.master_id, departed_at=now, status_history_id=history.id
        )
    )
    notify(db, order.client_id, "order.en_route", {"order_id": str(order.id)})
    db.commit()
    return order


def arrive(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("en_route",))
    if order.arrived_at is None:
        order.arrived_at = datetime.now(UTC)
        record_event(db, "order.arrived", "order", order.id, "user", user.id)
        notify(db, order.client_id, "order.arrived", {"order_id": str(order.id)})
    db.commit()
    return order


def start_work(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("en_route",))
    now = datetime.now(UTC)
    order.arrived_at = order.arrived_at or now
    order.work_started_at = now
    order_status(db, order, "in_progress", "user", user.id)
    db.add(WorkSegment(order_id=order.id, started_at=now))
    db.add(Worksheet(order_id=order.id))
    master = _lock_master(db, order.master_id)
    master.is_busy, master.busy_since = True, now  # an active work sheet makes the master Busy (R-WS-05)
    db.commit()
    return order


def _open_segment(db: Session, order: Order) -> WorkSegment | None:
    return db.scalar(
        select(WorkSegment)
        .where(WorkSegment.order_id == order.id, WorkSegment.ended_at.is_(None))
        .with_for_update()
    )


def pause(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("in_progress",))
    segment = _open_segment(db, order)
    if segment is None:
        raise conflict("ALREADY_PAUSED", "The work is already paused.")
    segment.ended_at = datetime.now(UTC)
    record_event(db, "work.paused", "order", order.id, "user", user.id)
    db.commit()
    return order


def resume(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("in_progress",))
    if order.work_completed_at is not None:
        raise conflict("WORK_FINISHED", "The work is already finished.")
    if _open_segment(db, order) is not None:
        raise conflict("NOT_PAUSED", "The work is running.")
    db.add(WorkSegment(order_id=order.id, started_at=datetime.now(UTC)))
    record_event(db, "work.resumed", "order", order.id, "user", user.id)
    db.commit()
    return order


def finish_work(db: Session, user: User, order_id: uuid.UUID) -> Order:
    order = _transition(db, user, order_id, ("in_progress",))
    now = datetime.now(UTC)
    segment = _open_segment(db, order)
    if segment is not None:
        segment.ended_at = now
    order.work_completed_at = order.work_completed_at or now
    record_event(db, "work.finished", "order", order.id, "user", user.id)
    db.commit()
    return order


def billable_seconds(db: Session, order_id: uuid.UUID, now: datetime | None = None) -> int:
    """Actual work time only: the sum of work segments. Travel is never added (K-7). Rounding is applied
    separately by services/billable.py (Q-01)."""
    now = _now(now)
    total = 0
    for segment in db.scalars(select(WorkSegment).where(WorkSegment.order_id == order_id)):
        total += int(((segment.ended_at or now) - segment.started_at).total_seconds())
    return max(total, 0)


def worksheet(db: Session, order: Order) -> Worksheet | None:
    return db.scalar(select(Worksheet).where(Worksheet.order_id == order.id))


def update_worksheet(
    db: Session,
    user: User,
    order_id: uuid.UUID,
    *,
    work_description: str | None,
    limitations: str | None,
    temporary: bool,
    internal_notes: str | None,
    materials: list[dict[str, object]],
    external_costs: Decimal,
) -> Worksheet:
    order = _transition(db, user, order_id, ("in_progress",))
    sheet = worksheet(db, order)
    if sheet is None or sheet.state != "draft":
        raise conflict("WORKSHEET_FINALISED", "The work sheet is already final.")
    sheet.work_description = (work_description or "").strip() or None
    sheet.limitations_explained = (limitations or "").strip() or None
    sheet.is_temporary_repair = temporary
    sheet.internal_notes = (internal_notes or "").strip() or None
    sheet.external_costs_eur = eur(external_costs)
    db.query(WorksheetMaterial).filter(WorksheetMaterial.worksheet_id == sheet.id).delete()
    total = Decimal("0")
    for item in materials:
        amount = eur(item["amount_eur"])  # type: ignore[arg-type]
        total += amount
        db.add(
            WorksheetMaterial(
                worksheet_id=sheet.id,
                name=str(item["name"]),
                quantity=Decimal(str(item["quantity"])),
                unit=(str(item["unit"]) if item.get("unit") else None),
                amount_eur=amount,
            )
        )
    sheet.materials_amount_eur = eur(total)
    sheet.version += 1
    db.commit()
    return sheet


def finalise(db: Session, user: User, order_id: uuid.UUID) -> Order:
    """Final work sheet → labour from actual work time with the 40 € floor → one commission charge.

    Idempotent: a repeated call on a completed order changes nothing (and the unique index forbids a second
    charge in any case).
    """
    order = own_order(db, user, order_id, lock=True)
    if order.status in ("completed", "reviewed"):
        return order
    if order.status != "in_progress":
        raise conflict("INVALID_TRANSITION", f"Not possible while the order is {order.status}.")
    if order.work_completed_at is None:
        raise conflict("WORK_NOT_FINISHED", "Finish the work first.")
    sheet = worksheet(db, order)
    if sheet is None or not sheet.work_description:
        raise AppError(
            "WORKSHEET_INCOMPLETE", "Describe the work done.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    master = _lock_master(db, order.master_id)
    now = datetime.now(UTC)
    raw_seconds = billable_seconds(db, order.id, now)
    rule = billable.current_rule(db)
    seconds = billable.apply(raw_seconds, rule)
    labour = labour_amount(order.hourly_rate_snapshot, order.minimum_order_snapshot, seconds)
    charge = commission_amount(order.commission_rate_snapshot, labour)
    travel = (
        int((order.arrived_at - order.en_route_at).total_seconds() // 60)
        if order.arrived_at and order.en_route_at
        else None
    )
    sheet.billable_seconds, sheet.travel_minutes = seconds, travel
    sheet.labour_amount_eur, sheet.commission_eur = labour, charge
    sheet.calculation = {
        "hourly_rate_eur": str(order.hourly_rate_snapshot),
        "minimum_order_eur": str(order.minimum_order_snapshot),
        "billable_seconds": seconds,
        "actual_work_seconds": raw_seconds,
        "billable_rule": rule.as_dict(),
        "by_time_eur": str(eur(order.hourly_rate_snapshot * Decimal(seconds) / Decimal(3600))),
        "minimum_applied": labour == eur(order.minimum_order_snapshot)
        and seconds * order.hourly_rate_snapshot / 3600 < order.minimum_order_snapshot,
        "commission_rate": str(order.commission_rate_snapshot),
        "rule_note": "Billable time = actual work segments, no travel, rounded by billable_rule (Q-01).",
    }
    sheet.state, sheet.finalised_at = "finalised", now
    order.completed_at = now
    order_status(db, order, "completed", "user", user.id)
    commission.record_charge(db, master.id, order.id, labour, order.commission_rate_snapshot, charge)
    master.is_busy, master.busy_since = False, None
    master.completed_jobs += 1
    record_event(
        db,
        "worksheet.finalised",
        "order",
        order.id,
        "user",
        user.id,
        {"labour_eur": str(labour), "commission_eur": str(charge)},
    )
    notify(db, order.client_id, "order.completed", {"order_id": str(order.id)})
    db.commit()
    return order


def review(db: Session, user: User, order_id: uuid.UUID, rating: int, comment: str | None) -> Review:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.client_id == user.id).with_for_update())
    if order is None:
        raise AppError("NOT_FOUND", "Order not found.", status.HTTP_404_NOT_FOUND)
    if order.status != "completed":
        raise conflict("CANNOT_REVIEW", "Only a completed order can be reviewed once.")
    master = _lock_master(db, order.master_id)
    row = Review(
        order_id=order.id,
        client_id=user.id,
        master_id=master.id,
        rating=rating,
        comment=(comment or "").strip() or None,
    )
    db.add(row)
    count = master.rating_count + 1
    master.rating_avg = ((master.rating_avg or Decimal(0)) * master.rating_count + rating) / count
    master.rating_avg = master.rating_avg.quantize(Decimal("0.01"))
    master.rating_count = count
    order_status(db, order, "reviewed", "user", user.id)
    db.commit()
    return row


def admin_cancel(db: Session, admin: User, request_id: uuid.UUID, reason: str) -> ServiceRequest:
    request = _lock_request(db, request_id)
    if request.status in ("cancelled", "unserved"):
        raise conflict("CANNOT_CANCEL", "The request is already closed.")
    cancel_for_request(db, request, "admin", admin.id, reason)
    record_audit(
        db, "request.cancelled_by_admin", "service_request", request.id, "user", admin.id, reason=reason
    )
    db.commit()
    return request


def count_open(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Order).where(Order.status.in_(LIVE))) or 0
