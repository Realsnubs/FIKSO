"""Deterministic matching (D2, R-MATCH, ARCHITECTURE §6). AI never selects masters.

One round = one `matching_runs` row (≤ 3 per request). The proposal is shown to the client first (option A);
showing it never blocks the master. Candidates are filtered by the shared eligibility rule and then by the
matching-only conditions: city, language, mode, Busy, fresh location for immediate requests, commission limit,
explicit decline for this request and overlapping blocking orders.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.integrations.maps import distance_km, fallback_eta_minutes, get_routing, safe_eta
from app.models import (
    City,
    MasterCity,
    MasterLanguage,
    MasterLocation,
    MasterProfile,
    MatchingCandidate,
    MatchingRun,
    Order,
    OrderOffer,
    ServiceRequest,
    User,
)
from app.models.orders import BLOCKING_STATUSES
from app.services import eligibility, settings
from app.services.commission import balance_expr
from app.services.events import record_event
from app.services.lifecycle import request_status
from app.services.notifications import notify

MODES_FOR = {"immediate": ("available_now",), "reserved": ("available_now", "available_for_reservations")}


@dataclass
class Candidate:
    master_id: uuid.UUID
    user_id: uuid.UUID
    distance_km: float
    eta_minutes: int
    eta_source: str
    rating_avg: Decimal | None
    completed_jobs: int
    origin: tuple[float, float] = (0.0, 0.0)


def block_range(
    db: Session, request: ServiceRequest, eta_minutes: int, now: datetime
) -> tuple[Range[datetime], datetime, datetime]:
    """The interval an offer to this request would block: (busy_range, estimated_start, estimated_end).

    Forecast only — never the billable time (K-7). The buffer and the immediate-job duration are open (Q-D2-1)
    and come from settings.
    """
    buffer = timedelta(minutes=int(settings.get(db, "order_buffer_minutes")))
    if request.request_type == "immediate":
        start = now + timedelta(minutes=eta_minutes)
        end = start + timedelta(minutes=int(settings.get(db, "immediate_job_minutes")))
        return Range(now, end + buffer, bounds="[)"), start, end
    assert request.preferred_time_from and request.preferred_time_to
    start, end = request.preferred_time_from, request.preferred_time_to
    return Range(start - buffer, end + buffer, bounds="[)"), start, end


def _declined(request_id: uuid.UUID) -> Any:
    return (
        select(Order.master_id)
        .join(OrderOffer, OrderOffer.order_id == Order.id)
        .where(Order.request_id == request_id, OrderOffer.response == "declined")
    )


def _overlapping(candidate_range: Range[datetime], now: datetime) -> Any:
    """Masters with a blocking order overlapping the range; offers past their expiry no longer count."""
    return (
        select(Order.master_id)
        .outerjoin(OrderOffer, OrderOffer.order_id == Order.id)
        .where(
            Order.status.in_(BLOCKING_STATUSES),
            Order.busy_range.overlaps(candidate_range),
            or_(Order.status != "offered", OrderOffer.expires_at > now),
        )
    )


def candidates(
    db: Session, request: ServiceRequest, now: datetime, only_master: uuid.UUID | None = None
) -> tuple[list[Candidate], dict[str, int], int]:
    """(ranked candidates, excluded counts by reason, eligible count). Same filter for the snapshot
    and the re-check."""
    params = settings.get(db, "matching")
    eligible_ids = set(eligibility.eligible_master_ids(db, request.service_id))
    if only_master is not None:
        eligible_ids &= {only_master}
    excluded: dict[str, int] = {}

    def drop(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    if not eligible_ids:
        return [], excluded, 0
    if request.city_code is None:
        # A request without a known city is never matched by guesswork (requests created before 2026-11-05).
        excluded["no_request_city"] = len(eligible_ids)
        return [], excluded, len(eligible_ids)
    rough_range, _, _ = block_range(db, request, 0, now)
    declined = set(db.scalars(_declined(request.id)))
    overlapping = set(db.scalars(_overlapping(rough_range, now)))
    fresh_after = now - timedelta(minutes=int(params["location_fresh_minutes"]))
    city_query = select(MasterCity.master_id, MasterCity.city_code).where(
        MasterCity.master_id.in_(eligible_ids), MasterCity.is_primary.is_(True)
    )
    city_of: dict[uuid.UUID, str] = {master_id: code for master_id, code in db.execute(city_query)}
    languages_of: dict[uuid.UUID, set[str]] = {}
    language_query = select(MasterLanguage.master_id, MasterLanguage.language_code).where(
        MasterLanguage.master_id.in_(eligible_ids)
    )
    for master_id, code in db.execute(language_query):
        languages_of.setdefault(master_id, set()).add(code)
    centres = {c.code: (float(c.lat), float(c.lon)) for c in db.scalars(select(City))}
    rows = db.execute(
        select(MasterProfile, MasterLocation, balance_expr().label("balance"))  # type: ignore[attr-defined]
        .join(User, User.id == MasterProfile.user_id)
        .outerjoin(MasterLocation, MasterLocation.master_id == MasterProfile.id)
        .where(MasterProfile.id.in_(eligible_ids))
    ).all()
    point = (float(request.lat), float(request.lon))
    found: list[Candidate] = []
    # Order (owner decision 2026-11-05): city → eligibility (above) → language → availability/Busy →
    # immediate-request location → commission limit → this request's declines and overlapping offers.
    for profile, location, balance in rows:
        master_city = city_of.get(profile.id)
        if master_city != request.city_code:
            drop("city")  # also a master without a city: never matched in every city
            continue
        spoken = languages_of.get(profile.id, set())
        if not spoken or (request.communication_language and request.communication_language not in spoken):
            drop("language")
            continue
        if profile.availability_mode not in MODES_FOR[request.request_type]:
            drop("mode")
            continue
        if profile.is_busy:
            drop("busy")
            continue
        fresh = location is not None and location.updated_at >= fresh_after
        if request.request_type == "immediate" and not fresh:
            drop("stale_location")
            continue
        if Decimal(balance) >= profile.commission_limit_eur:
            drop("limit")
            continue
        if profile.id in declined:
            drop("declined_this_request")
            continue
        if profile.id in overlapping:
            drop("overlapping_offer")
            continue
        # ETA from the latest location; without a fresh one, from the centre of the master's city.
        origin = (float(location.lat), float(location.lon)) if fresh and location else centres[master_city]
        found.append(
            Candidate(
                profile.id,
                profile.user_id,
                distance_km(*origin, *point),
                0,
                "fallback",
                profile.rating_avg,
                profile.completed_jobs,
                origin,
            )
        )
    found.sort(key=lambda c: (c.distance_km, str(c.master_id)))
    top = found[: int(params["top_k"])]
    # One batched provider call for all candidates; failures and missing providers fall back per candidate.
    etas = safe_eta(get_routing(), [c.origin for c in top], point)
    for c, eta in zip(top, etas, strict=True):
        if (
            eta is None
        ):  # no routing provider (Q-02), provider down, or no route: straight line at the fallback speed
            c.eta_minutes, c.eta_source = (
                fallback_eta_minutes(c.distance_km, float(params["fallback_speed_kmh"])),
                "fallback",
            )
        else:
            c.eta_minutes, c.eta_source = eta, "routing"
    top.sort(
        key=lambda c: (
            c.eta_minutes,
            -(c.rating_avg or Decimal(0)),
            -c.completed_jobs,
            c.distance_km,
            str(c.master_id),
        )
    )
    return top, excluded, len(eligible_ids)


def open_run(db: Session, request: ServiceRequest) -> MatchingRun | None:
    return db.scalar(
        select(MatchingRun)
        .where(MatchingRun.request_id == request.id, MatchingRun.closed_at.is_(None))
        .order_by(MatchingRun.created_at.desc())
        .limit(1)
    )


# After the client confirms, the round's final outcome is the master's answer (or a cancellation).
_AFTER_CONFIRMATION = ("master_accepted", "master_declined", "master_expired", "cancelled")


def close_run(run: MatchingRun, reason: str, now: datetime) -> None:
    if run.closed_at is None or (run.close_reason == "client_confirmed" and reason in _AFTER_CONFIRMATION):
        run.closed_at, run.close_reason = now, reason


def start_round(
    db: Session, request: ServiceRequest, now: datetime | None = None, *, retry: bool = False
) -> MatchingRun | None:
    """Run the next round (or, with `retry`, a technical re-run of the current one). Caller holds the
    request lock."""
    now = now or datetime.now(UTC)
    params = settings.get(db, "matching")
    if not retry and request.current_round >= int(params["max_rounds"]):
        _unserved(db, request, "rounds_exhausted")
        return None
    if not retry or request.current_round == 0:
        request.current_round += 1
    attempt = 1 + (
        db.scalar(
            select(func.count())
            .select_from(MatchingRun)
            .where(MatchingRun.request_id == request.id, MatchingRun.run_no == request.current_round)
        )
        or 0
    )
    found, excluded, eligible_count = candidates(db, request, now)
    run = MatchingRun(
        request_id=request.id,
        run_no=request.current_round,
        attempt=attempt,
        request_type=request.request_type,
        eligible_count=eligible_count,
        available_count=len(found),
        excluded_counts=excluded,
        params={
            k: params[k]
            for k in ("top_k", "fallback_speed_kmh", "alternative_margin_minutes", "max_alternatives")
        },
        outcome="proposed" if found else "no_candidates",
    )
    db.add(run)
    db.flush()
    margin = int(params["alternative_margin_minutes"])
    shown = 0
    for rank, c in enumerate(found, start=1):
        if rank == 1:
            role = "proposal"
        elif shown <= int(params["max_alternatives"]) and c.eta_minutes <= found[0].eta_minutes + margin:
            role = "alternative"
        else:
            role = "not_shown"
        if role != "not_shown":
            shown += 1
        db.add(
            MatchingCandidate(
                matching_run_id=run.id,
                master_id=c.master_id,
                rank=rank,
                distance_km=Decimal(f"{c.distance_km:.2f}"),
                eta_minutes=c.eta_minutes,
                eta_source=c.eta_source,
                rating_avg=c.rating_avg,
                completed_jobs=c.completed_jobs,
                role_in_result=role,
            )
        )
    record_event(
        db,
        "matching.completed",
        "service_request",
        request.id,
        "system",
        None,
        {
            "run_no": run.run_no,
            "attempt": attempt,
            "eligible": eligible_count,
            "available": len(found),
            "excluded": excluded,
        },
    )
    if not found:
        run.closed_at = now
        _unserved(db, request, "no_candidates")
        return run
    minutes = settings.get(db, "client_confirmation_minutes")[request.request_type]
    run.proposal_expires_at = now + timedelta(minutes=int(minutes))
    request_status(db, request, "proposed", "system", None, payload={"run_no": run.run_no})
    notify(db, request.client_id, "proposal.ready", {"request_id": str(request.id), "run_no": run.run_no})
    return run


def _unserved(db: Session, request: ServiceRequest, reason: str) -> None:
    request.unserved_reason = reason
    request_status(db, request, "unserved", "system", None, reason=reason)
    notify(db, request.client_id, "request.unserved", {"request_id": str(request.id)})


def next_round(db: Session, request: ServiceRequest, now: datetime | None = None) -> None:
    """After a failed round (client did not confirm or rejected, master declined or let the offer expire)."""
    if request.status != "matching":
        request_status(db, request, "matching", "system", None)
    start_round(db, request, now)


def proposal(
    db: Session, request: ServiceRequest
) -> tuple[MatchingRun, list[tuple[MatchingCandidate, MasterProfile, User]]] | None:
    run = open_run(db, request)
    if run is None or run.outcome != "proposed" or request.status != "proposed":
        return None
    rows = db.execute(
        select(MatchingCandidate, MasterProfile, User)
        .join(MasterProfile, MasterProfile.id == MatchingCandidate.master_id)
        .join(User, User.id == MasterProfile.user_id)
        .where(MatchingCandidate.matching_run_id == run.id, MatchingCandidate.role_in_result != "not_shown")
        .order_by(MatchingCandidate.rank)
    ).all()
    return run, [(c, m, u) for c, m, u in rows]
