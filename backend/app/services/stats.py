"""Admin statistics (C7): counted from the real tables, nothing estimated."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CatalogueService,
    CommissionLedgerEntry,
    JobRun,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    MatchingRun,
    Order,
    PublicEvent,
    ServiceRequest,
    User,
)
from app.services import catalogue


def _grouped(db: Session, column: Any, *where: Any) -> dict[str, int]:
    query = select(column, func.count()).group_by(column)
    for condition in where:
        query = query.where(condition)
    return {str(k): int(v) for k, v in db.execute(query).all()}


def overview(db: Session, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    available = catalogue.availability(db)
    run_reasons = _grouped(db, MatchingRun.close_reason, MatchingRun.created_at >= since)
    outcomes = _grouped(db, MatchingRun.outcome, MatchingRun.created_at >= since)
    ledger = dict(
        db.execute(
            select(
                CommissionLedgerEntry.entry_type, func.coalesce(func.sum(CommissionLedgerEntry.amount_eur), 0)
            )
            .where(CommissionLedgerEntry.created_at >= since)
            .group_by(CommissionLedgerEntry.entry_type)
        ).all()
    )
    total_balance = db.scalar(select(func.coalesce(func.sum(CommissionLedgerEntry.amount_eur), 0)))
    stale_jobs = db.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.status == "running", JobRun.started_at < datetime.now(UTC) - timedelta(minutes=10))
    )
    last_job = db.scalar(select(func.max(JobRun.finished_at)))
    return {
        "period_days": days,
        "queue": {
            "masters_pending": db.scalar(
                select(func.count())
                .select_from(MasterProfile)
                .where(MasterProfile.approval_status == "pending_approval")
            ),
            "specialisations_requested": db.scalar(
                select(func.count())
                .select_from(MasterSpecialisation)
                .where(MasterSpecialisation.status == "requested")
            ),
            "qualifications_submitted": db.scalar(
                select(func.count())
                .select_from(MasterQualification)
                .where(MasterQualification.status == "submitted")
            ),
        },
        "users": _grouped(db, User.role),
        "masters": _grouped(db, MasterProfile.approval_status),
        "masters_by_mode": _grouped(
            db, MasterProfile.availability_mode, MasterProfile.approval_status == "approved"
        ),
        "catalogue": {
            "services_by_status": _grouped(db, CatalogueService.status),
            "orderable_services": sum(1 for a in available.values() if a.orderable),
        },
        "public": _grouped(db, PublicEvent.event_type, PublicEvent.created_at >= since),
        "requests": {
            "by_status": _grouped(db, ServiceRequest.status, ServiceRequest.created_at >= since),
            "by_source": _grouped(db, ServiceRequest.source, ServiceRequest.created_at >= since),
        },
        "matching": {"outcomes": outcomes, "round_endings": run_reasons},
        "orders": _grouped(db, Order.status, Order.created_at >= since),
        "commission": {
            "charged_eur": str(ledger.get("charge", 0)),
            "paid_eur": str(-ledger.get("payment", 0)),
            "outstanding_eur": str(total_balance),
        },
        "worker": {"last_finished_at": last_job.isoformat() if last_job else None, "stuck_runs": stale_jobs},
    }
