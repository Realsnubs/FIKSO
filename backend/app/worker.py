"""Background worker (owner decision Q-FINAL-03): a separate process, `python -m app.cli run-jobs`.

Every job picks due rows with `FOR UPDATE SKIP LOCKED`, so several worker processes never take the same row,
and handles each row in its own transaction; every handler re-checks the state under its locks, so a repeated
or concurrent run changes nothing (idempotent). Each pass is recorded in `job_runs`; a run left `running` by a
crashed worker is marked failed on the next start (stuck-job detection). Request handlers do not depend on the
worker for correctness: expired offers never block a master (`expires_at > now()` is part of every check).
"""

import logging
import os
import socket
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, select, text, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import JobRun, MatchingRun, Notification, Order, OrderOffer, ServiceRequest
from app.services import matching, orders

if TYPE_CHECKING:
    from app.integrations.sms import SmsSender

logger = logging.getLogger("fikso.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
STALE_AFTER = timedelta(minutes=10)
BATCH = 50
MAX_ATTEMPTS = 6
_CONFIGURED = object()  # deliver_notifications: use the provider from the configuration


def _due_ids(db: Session, query: object) -> list[uuid.UUID]:
    return list(db.scalars(query.limit(BATCH).with_for_update(skip_locked=True)))  # type: ignore[attr-defined]


def expire_proposals(now: datetime) -> int:
    done = 0
    with SessionLocal() as db:
        ids = _due_ids(
            db,
            select(MatchingRun.id).where(
                MatchingRun.closed_at.is_(None),
                MatchingRun.outcome == "proposed",
                MatchingRun.proposal_expires_at <= now,
            ),
        )
        db.rollback()
    for run_id in ids:
        with SessionLocal() as db:
            done += orders.expire_proposal(db, run_id, now)
    return done


def expire_offers(now: datetime) -> int:
    done = 0
    with SessionLocal() as db:
        ids = _due_ids(
            db,
            select(Order.id)
            .join(OrderOffer, OrderOffer.order_id == Order.id)
            .where(Order.status == "offered", OrderOffer.response.is_(None), OrderOffer.expires_at <= now),
        )
        db.rollback()
    for order_id in ids:
        with SessionLocal() as db:
            done += orders.expire_offer(db, order_id, now)
    return done


def recover_requests(now: datetime) -> int:
    """Crash recovery: a request left `matching` (no open round) or `confirmed` without a live order gets its
    next round. Normal paths never leave this state; it only appears after an interrupted transaction."""
    done = 0
    with SessionLocal() as db:
        # Any order not ended unsuccessfully counts: a completed order closes the request for good.
        live = (
            select(Order.id)
            .where(Order.request_id == ServiceRequest.id, Order.status.not_in(orders.ENDED_UNSUCCESSFULLY))
            .exists()
        )
        open_run = (
            select(MatchingRun.id)
            .where(MatchingRun.request_id == ServiceRequest.id, MatchingRun.closed_at.is_(None))
            .exists()
        )
        ids = _due_ids(
            db,
            select(ServiceRequest.id).where(
                ((ServiceRequest.status == "confirmed") & ~live)
                | ((ServiceRequest.status == "matching") & ~open_run),
                ServiceRequest.updated_at <= now - timedelta(minutes=1),
            ),
        )
        db.rollback()
    for request_id in ids:
        with SessionLocal() as db:
            request = db.scalar(
                select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
            )
            if (
                request is None
                or request.status not in ("confirmed", "matching")
                or orders.has_order(db, request.id)
            ):
                continue
            if request.status == "matching" and matching.open_run(db, request):
                continue
            matching.next_round(db, request, now)
            db.commit()
            done += 1
    return done


def deliver_notifications(now: datetime, sender: "SmsSender | None | object" = _CONFIGURED) -> int:
    """SMS outbox.

    A row becomes `sent` only when the provider accepted it and returned a message ID. Temporary failures
    retry with exponential backoff (MAX_ATTEMPTS); permanent ones fail at once. Without a provider the row is
    marked `skipped`, never reported as sent. The attempt is committed with a later `next_attempt_at`
    before the provider is called, so a crash mid-call cannot trigger an immediate duplicate send.
    """
    from app.integrations.sms import SmsError, get_sms_sender
    from app.services.notifications import SMS_TEXTS

    active = get_sms_sender() if sender is _CONFIGURED else sender
    done = 0
    with SessionLocal() as db:
        ids = list(
            db.scalars(
                select(Notification.id)
                .where(
                    Notification.channel == "sms",
                    Notification.status == "pending",
                    (Notification.next_attempt_at.is_(None)) | (Notification.next_attempt_at <= now),
                )
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        db.rollback()
    for notification_id in ids:
        with SessionLocal() as db:
            row = db.scalar(
                select(Notification)
                .where(Notification.id == notification_id)
                .with_for_update(skip_locked=True)
            )
            if row is None or row.status != "pending":
                continue
            if active is None:
                row.status, row.last_error = "skipped", "no SMS provider configured"
                db.commit()
                continue
            from app.models import User

            phone = db.scalar(select(User.phone).where(User.id == row.user_id))
            text = SMS_TEXTS.get(row.type)
            if not phone or not text:
                row.status, row.last_error = "failed", "no phone number" if not phone else "no text"
                db.commit()
                continue
            row.attempts += 1
            row.next_attempt_at = now + timedelta(minutes=5)
            db.commit()
            try:
                accepted = cast("SmsSender", active).send(phone, text, str(row.id))
            except SmsError as exc:
                row.last_error = str(exc)[:200]
                if exc.permanent or row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    logger.error("sms %s failed permanently", row.id)
                else:
                    row.next_attempt_at = now + timedelta(seconds=30 * 2**row.attempts)
                    logger.warning("sms %s attempt %d failed, retrying", row.id, row.attempts)
                db.commit()
                continue
            row.status, row.sent_at = "sent", datetime.now(UTC)
            row.provider, row.provider_message_id, row.last_error = (
                accepted.provider,
                accepted.message_id,
                None,
            )
            db.commit()
            done += 1
    return done


def purge_rate_limits(now: datetime) -> int:
    """Old rate-limit windows are useless; keep the table small."""
    with SessionLocal() as db:
        result = db.execute(
            text("DELETE FROM rate_limit_counters WHERE window_start < :cutoff"),
            {"cutoff": now - timedelta(hours=1)},
        )
        db.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


JOBS: dict[str, Callable[[datetime], int]] = {
    "expire_proposals": expire_proposals,
    "expire_offers": expire_offers,
    "recover_requests": recover_requests,
    "deliver_notifications": deliver_notifications,
    "purge_rate_limits": purge_rate_limits,
}


def mark_stale_runs(now: datetime) -> int:
    with SessionLocal() as db:
        result = db.execute(
            update(JobRun)
            .where(and_(JobRun.status == "running", JobRun.started_at < now - STALE_AFTER))
            .values(status="failed", finished_at=now, error="stale: worker stopped during the run")
        )
        db.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def run_once(now: datetime | None = None) -> dict[str, int]:
    results = {}
    for name, job in JOBS.items():
        started = now or datetime.now(UTC)
        with SessionLocal() as db:
            run = JobRun(job_name=name, worker_id=WORKER_ID, started_at=started, status="running")
            db.add(run)
            db.commit()
            run_id = run.id
        status, error, count = "succeeded", None, 0
        try:
            count = job(now or datetime.now(UTC))
        except Exception as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            logger.exception("job %s failed", name)
        with SessionLocal() as db:
            db.execute(
                update(JobRun)
                .where(JobRun.id == run_id)
                .values(status=status, error=error, items_processed=count, finished_at=datetime.now(UTC))
            )
            db.commit()
        results[name] = count
    return results


def run_forever(interval_seconds: float = 30.0) -> None:
    from sqlalchemy.exc import OperationalError

    logger.info("worker %s started", WORKER_ID)
    stale_checked = False
    while True:
        # A database outage skips the pass instead of ending the process: every job is transactional and
        # picks up where it left off (expired timers, the outbox) once the database is back.
        try:
            if not stale_checked:
                stale = mark_stale_runs(datetime.now(UTC))
                stale_checked = True
                if stale:
                    logger.warning("marked %d stale job runs as failed", stale)
            run_once()
        except OperationalError as exc:
            logger.warning("database unavailable, pass skipped: %s", type(exc.orig or exc).__name__)
        time.sleep(interval_seconds)
