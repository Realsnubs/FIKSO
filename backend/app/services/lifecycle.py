"""Status history of requests and orders: every transition is logged with its domain event in one
transaction."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Order, OrderStatusHistory, ServiceRequest
from app.services.events import record_event


def request_status(
    db: Session,
    request: ServiceRequest,
    to_status: str,
    actor_type: str,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    from_status = request.status
    request.status = to_status
    request.version += 1
    db.add(
        OrderStatusHistory(
            request_id=request.id,
            entity="request",
            from_status=from_status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )
    )
    record_event(
        db,
        "request.status_changed",
        "service_request",
        request.id,
        actor_type,
        actor_id,
        {"from": from_status, "to": to_status, "reason": reason, **(payload or {})},
    )


def order_status(
    db: Session,
    order: Order,
    to_status: str,
    actor_type: str,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
) -> OrderStatusHistory:
    from_status = order.status if order.status else None
    order.status = to_status
    order.version += 1
    row = OrderStatusHistory(
        order_id=order.id,
        request_id=order.request_id,
        entity="order",
        from_status=from_status,
        to_status=to_status,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
    )
    db.add(row)
    record_event(
        db,
        "order.status_changed",
        "order",
        order.id,
        actor_type,
        actor_id,
        {"from": from_status, "to": to_status, "reason": reason},
    )
    return row
