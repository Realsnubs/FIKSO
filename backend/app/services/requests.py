"""Client service requests (D1): draft, photos, submission, cancellation. Only the owner sees a request."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.integrations.images import ImageError, process_private
from app.integrations.maps import ProviderError, get_geocoder, in_latvia
from app.integrations.storage import Storage
from app.models import Attachment, CatalogueService, CatalogueSpecialisation, ServiceRequest, User
from app.schemas.requests import RequestCreateIn, RequestUpdateIn
from app.services import catalogue, commercial, places, settings
from app.services.events import record_audit, record_event
from app.services.lifecycle import request_status
from app.services.public_catalogue import NOT_AVAILABLE
from app.services.uploads import ValidFile, _read_limited, store_attachments

# The only accepted entry sources (owner decision, src=web); anything else counts as the app itself.
ENTRY_SOURCES = {"web": "website_deeplink"}
MAX_AHEAD = timedelta(days=60)
CANCELLABLE = ("draft", "matching", "proposed", "confirmed")


def entry_source(src: str | None) -> str:
    return ENTRY_SOURCES.get((src or "").strip().lower(), "app")


def _orderable(db: Session, service: CatalogueService) -> None:
    if not catalogue.availability(db, [service.id])[service.id].orderable:
        raise NOT_AVAILABLE


def _snapshot(service: CatalogueService) -> dict[str, str]:
    spec = service.specialisation
    return {
        "service_id": str(service.id),
        "w_id": service.w_id,
        "service_name": service.name,
        "specialisation_id": str(spec.id),
        "specialisation_name": spec.name,
        "category_id": str(spec.category.id),
        "category_name": spec.category.name,
    }


def get_own(db: Session, user: User, request_id: uuid.UUID, lock: bool = False) -> ServiceRequest:
    query = select(ServiceRequest).where(ServiceRequest.id == request_id, ServiceRequest.client_id == user.id)
    request = db.scalar(query.with_for_update() if lock else query)
    if request is None:
        raise AppError("NOT_FOUND", "Request not found.", status.HTTP_404_NOT_FOUND)
    return request


def create(db: Session, user: User, data: RequestCreateIn, idempotency_key: str | None) -> ServiceRequest:
    if idempotency_key:
        existing = db.scalar(
            select(ServiceRequest).where(
                ServiceRequest.client_id == user.id, ServiceRequest.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
    service = db.scalar(
        select(CatalogueService)
        .options(selectinload(CatalogueService.specialisation).selectinload(CatalogueSpecialisation.category))
        .where(CatalogueService.w_id == data.w_id.upper())
    )
    if service is None:
        raise NOT_AVAILABLE
    _orderable(db, service)
    city = places.get_city(db, data.city)
    language = places.check_language(db, data.communication_language)
    now = datetime.now(UTC)
    if data.request_type == "reserved":
        assert data.preferred_time_from and data.preferred_time_to
        if data.preferred_time_from < now or data.preferred_time_to > now + MAX_AHEAD:
            raise AppError(
                "INVALID_TIME_WINDOW",
                "Choose a time window in the next 60 days.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
    if data.lat is not None and data.lon is not None:
        if not in_latvia(float(data.lat), float(data.lon)):
            raise AppError(
                "ADDRESS_OUTSIDE_AREA", "FIKSO works in Latvia only.", status.HTTP_422_UNPROCESSABLE_CONTENT
            )
        lat, lon, source = data.lat, data.lon, "device"
    else:
        try:
            point = get_geocoder().geocode(data.address)
        except ProviderError as exc:
            # Provider down or not configured: say so truthfully; the device location still works.
            raise AppError(
                "GEOCODING_UNAVAILABLE",
                "Address search is unavailable right now. Use your current location instead.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc
        if point is None:
            raise AppError(
                "ADDRESS_NOT_FOUND",
                "The address could not be located precisely. Check it or use your current location.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        lat, lon, source = point.lat, point.lon, point.source
    if not places.point_in_city(city, float(lat), float(lon)):
        # The point does not belong to the chosen city: matching would rest on a guess, so ask the client.
        raise AppError(
            "CITY_MISMATCH",
            "The address is not in the chosen city. Check the city or the address.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    request = ServiceRequest(
        city_code=city.code,
        communication_language=language,
        client_id=user.id,
        service_id=service.id,
        catalogue_snapshot=_snapshot(service),
        description=data.description,
        request_type=data.request_type,
        preferred_time_from=data.preferred_time_from,
        preferred_time_to=data.preferred_time_to,
        address_formatted=data.address,
        flat=data.flat,
        access_info=data.access_info,
        lat=lat,
        lon=lon,
        geocode_source=source,
        source=entry_source(data.src),
        deeplink_w_id=service.w_id if entry_source(data.src) == "website_deeplink" else None,
        idempotency_key=idempotency_key,
    )
    db.add(request)
    db.flush()
    record_event(
        db,
        "request.created",
        "service_request",
        request.id,
        "user",
        user.id,
        {
            "w_id": service.w_id,
            "source": request.source,
            "request_type": request.request_type,
            "city": city.code,
            "language": language or "any",
        },
    )
    db.commit()
    return request


def update(db: Session, user: User, request_id: uuid.UUID, data: RequestUpdateIn) -> ServiceRequest:
    request = get_own(db, user, request_id, lock=True)
    _require_draft(request)
    if request.version != data.expected_version:
        raise AppError("VERSION_CONFLICT", "The request was changed meanwhile.", status.HTTP_409_CONFLICT)
    for field in ("description", "access_info", "flat"):
        value = getattr(data, field)
        if value is not None:
            setattr(request, field, value.strip() or None if field != "description" else value.strip())
    request.version += 1
    db.commit()
    return request


def _require_draft(request: ServiceRequest) -> None:
    if request.status != "draft":
        raise AppError("REQUEST_NOT_DRAFT", "Only a draft request can be changed.", status.HTTP_409_CONFLICT)


def photos(db: Session, request_id: uuid.UUID) -> list[Attachment]:
    return list(
        db.scalars(
            select(Attachment)
            .where(Attachment.entity_type == "request", Attachment.entity_id == request_id)
            .order_by(Attachment.uploaded_at)
        ).all()
    )


def add_photo(
    db: Session, storage: Storage, user: User, request_id: uuid.UUID, upload: UploadFile
) -> Attachment:
    """OQ-14/15/16: draft only; ≤ 5 photos; ≤ 10 MB; JPEG/PNG/WebP/HEIC; re-encoded to JPEG without
    metadata."""
    request = get_own(db, user, request_id, lock=True)
    _require_draft(request)
    limits = settings.get(db, "request_photos")
    count = db.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.entity_type == "request", Attachment.entity_id == request.id)
    )
    if (count or 0) >= int(limits["max_files"]):
        raise AppError(
            "TOO_MANY_FILES", "At most 5 photos per request.", details={"max_files": limits["max_files"]}
        )
    data = _read_limited(upload)
    if not data:
        raise AppError("FILE_EMPTY", "The file is empty.")
    try:
        processed = process_private(data)
    except ImageError as exc:
        raise AppError(
            "UNSUPPORTED_FILE_TYPE" if exc.code == "UNSUPPORTED_FILE_TYPE" else "INVALID_IMAGE",
            "Allowed formats: JPEG, PNG, WebP, HEIC.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        ) from exc
    file = ValidFile(processed.data, "image/jpeg", hashlib.sha256(processed.data).hexdigest())
    with store_attachments(
        db, storage, [file], owner_user_id=user.id, entity_type="request", entity_id=request.id
    ) as rows:
        db.commit()
    return rows[0]


def delete_photo(
    db: Session, storage: Storage, user: User, request_id: uuid.UUID, file_id: uuid.UUID
) -> None:
    request = get_own(db, user, request_id, lock=True)
    _require_draft(request)
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == file_id, Attachment.entity_type == "request", Attachment.entity_id == request.id
        )
    )
    if attachment is None:
        raise AppError("NOT_FOUND", "Photo not found.", status.HTTP_404_NOT_FOUND)
    key = attachment.storage_key
    db.delete(attachment)
    db.commit()
    storage.delete(key)


def submit(db: Session, user: User, request_id: uuid.UUID) -> ServiceRequest:
    """Re-checks availability without cache, freezes the commercial terms and starts matching (OQ-20)."""
    from app.services import matching

    request = get_own(db, user, request_id, lock=True)
    if request.status != "draft":
        return request  # idempotent: a repeated submit returns the current state
    service = db.scalar(select(CatalogueService).where(CatalogueService.id == request.service_id))
    assert service is not None
    _orderable(db, service)
    if (
        request.request_type == "reserved"
        and request.preferred_time_from
        and request.preferred_time_from < datetime.now(UTC)
    ):
        raise AppError(
            "INVALID_TIME_WINDOW",
            "The chosen time has already passed.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    request.commercial_terms_id = commercial.current(db).id
    request.submitted_at = datetime.now(UTC)
    request_status(db, request, "matching", "user", user.id)
    record_event(
        db, "request.submitted", "service_request", request.id, "user", user.id, {"w_id": service.w_id}
    )
    matching.start_round(db, request)
    db.commit()
    return request


def cancel(db: Session, user: User, request_id: uuid.UUID, reason: str | None) -> ServiceRequest:
    from app.services import orders

    request = get_own(db, user, request_id, lock=True)
    if request.status not in CANCELLABLE:
        raise AppError("CANNOT_CANCEL", "This request can no longer be cancelled.", status.HTTP_409_CONFLICT)
    orders.cancel_for_request(db, request, "client", user.id, reason)
    db.commit()
    return request


def log_photo_view(db: Session, actor: User, attachment: Attachment) -> None:
    record_audit(db, "attachment.viewed", "attachment", attachment.id, "user", actor.id)
    db.commit()
