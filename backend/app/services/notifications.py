"""Notifications (R-NOT): in-app rows are delivered by being stored; other channels go through the outbox,
which the background worker sends with retries (provider: SMS_PROVIDER, Q-08)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Notification, User

# Q-08 default: SMS only for a new offer (master) and for "accepted"/"on the way" (client). Latvian texts
# without personal data; their wording still needs the owner's approval.
SMS_TEXTS = {
    "offer.new": "FIKSO: jums ir jauns darba piedāvājums. Atveriet lietotni, lai atbildētu.",
    "order.accepted": "FIKSO: meistars pieņēma jūsu pasūtījumu. Detaļas lietotnē.",
    "order.en_route": "FIKSO: meistars ir ceļā pie jums.",
}


def notify(db: Session, user_id: uuid.UUID, type_: str, payload: dict[str, Any] | None = None) -> None:
    """Payloads hold IDs and status words only — never addresses, phones or coordinates.

    The in-app row is delivered by being stored. An SMS row is queued only when an SMS provider is configured;
    the worker sends it and it becomes `sent` only when the provider accepts it.
    """
    from app.integrations.sms import get_sms_sender

    now = datetime.now(UTC)
    db.add(
        Notification(
            user_id=user_id, type=type_, payload=payload or {}, channel="in_app", status="sent", sent_at=now
        )
    )
    if type_ in SMS_TEXTS and get_sms_sender() is not None:
        db.add(
            Notification(user_id=user_id, type=type_, payload=payload or {}, channel="sms", status="pending")
        )


def record_delivery(db: Session, provider_message_id: str, provider_status: str) -> bool:
    """Delivery report from the provider; unknown IDs are ignored (idempotent, safe to receive twice)."""
    from app.integrations.sms import DELIVERED, UNDELIVERED

    row = db.scalar(
        select(Notification).where(Notification.provider_message_id == provider_message_id).with_for_update()
    )
    if row is None:
        return False
    if provider_status in DELIVERED:
        row.status, row.delivered_at = "delivered", datetime.now(UTC)
    elif provider_status in UNDELIVERED:
        row.status, row.last_error = "undelivered", provider_status
    db.commit()
    return True


def list_for(db: Session, user: User, limit: int = 30) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id, Notification.channel == "in_app")
            .order_by(Notification.created_at.desc())
            .limit(limit)
        ).all()
    )


def mark_read(db: Session, user: User, ids: list[uuid.UUID] | None) -> None:
    query = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        query = query.where(Notification.id.in_(ids))
    db.execute(query.values(read_at=datetime.now(UTC), status="read"))
    db.commit()
