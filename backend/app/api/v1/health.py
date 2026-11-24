"""Liveness and readiness for the load balancer / orchestrator. No secrets and no personal data in answers."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select, text

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models import JobRun, Notification

router = APIRouter(tags=["ops"])


@router.get("/health")
@router.get("/health/live")
def live(db: DbSession) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def _migrations_current(db: DbSession) -> bool:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    current = set(db.scalars(text("SELECT version_num FROM alembic_version")))
    return current == heads


@router.get("/health/ready")
def ready(db: DbSession, response: Response) -> dict[str, Any]:
    """Critical checks decide 200/503 (database, migrations, both file stores). Providers, worker and the
    owner's unapproved policies are reported but do not take the API out of rotation."""
    from app.integrations.maps import get_geocoder, get_routing, routing_circuit
    from app.integrations.sms import get_sms_sender
    from app.integrations.storage import get_public_storage, get_storage
    from app.services import settings as app_settings

    checks: dict[str, Any] = {}
    critical_ok = True
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
        checks["migrations"] = "ok" if _migrations_current(db) else "behind"
        critical_ok &= checks["migrations"] == "ok"
    except Exception:  # noqa: BLE001 - readiness must answer, not crash
        checks["database"] = "unavailable"
        critical_ok = False
    for name, store in (("private_storage", get_storage), ("public_storage", get_public_storage)):
        try:
            store().check()  # type: ignore[attr-defined]
            checks[name] = "ok"
        except Exception:  # noqa: BLE001
            checks[name] = "unavailable"
            critical_ok = False
    settings = get_settings()
    checks["geocoder"] = type(get_geocoder()).__name__
    checks["routing"] = (
        get_routing().name if routing_circuit.available() else "fallback (provider cooling down)"
    )
    sender = get_sms_sender()
    checks["sms"] = sender.name if sender else "not configured"
    try:
        last = db.scalar(select(func.max(JobRun.finished_at)))
        checks["worker_last_run"] = last.isoformat() if last else None
        checks["worker"] = "ok" if last and last > datetime.now(UTC) - timedelta(minutes=5) else "stale"
        checks["sms_failed_24h"] = db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.channel == "sms",
                Notification.status.in_(("failed", "undelivered")),
                Notification.created_at > datetime.now(UTC) - timedelta(hours=24),
            )
        )
        checks["unconfirmed_policies"] = app_settings.unconfirmed_policies(db)
    except Exception:  # noqa: BLE001
        checks["worker"] = "unknown"
    checks["environment"] = settings.environment
    if not critical_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if critical_ok else "unavailable", "checks": checks}
