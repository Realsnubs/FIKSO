import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, DomainEvent


def record_event(
    db: Session,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    actor_type: str,
    actor_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append a domain event in the caller's transaction. Payloads must not contain raw personal data."""
    db.add(
        DomainEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload or {},
        )
    )


def record_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    actor_type: str,
    actor_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            before=before,
            after=after,
            reason=reason,
        )
    )
