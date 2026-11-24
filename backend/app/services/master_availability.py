"""Master availability, work city, languages and latest location (P1). Only the latest location is kept."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.integrations.maps import in_latvia
from app.models import MasterLocation, MasterProfile, User
from app.services import places, settings
from app.services.events import record_event

MODES = ("available_now", "available_for_reservations", "unavailable")


def own_profile(db: Session, user: User, lock: bool = False) -> MasterProfile:
    query = select(MasterProfile).where(MasterProfile.user_id == user.id)
    profile = db.scalar(query.with_for_update() if lock else query)
    if profile is None:
        raise AppError("NOT_FOUND", "Master profile not found.", status.HTTP_404_NOT_FOUND)
    return profile


def location_fresh(db: Session, location: MasterLocation | None, now: datetime | None = None) -> bool:
    if location is None:
        return False
    minutes = int(settings.get(db, "matching")["location_fresh_minutes"])
    return location.updated_at >= (now or datetime.now(UTC)) - timedelta(minutes=minutes)


def set_mode(db: Session, user: User, mode: str) -> MasterProfile:
    profile = own_profile(db, user, lock=True)
    if mode != "unavailable" and profile.approval_status != "approved":
        raise AppError("PROFILE_NOT_APPROVED", "Your profile is not approved yet.", status.HTTP_409_CONFLICT)
    if mode != "unavailable" and places.master_city_code(db, profile.id) is None:
        raise AppError("WORK_CITY_REQUIRED", "Choose your work city first.", status.HTTP_409_CONFLICT)
    if mode != "unavailable" and not places.master_language_codes(db, profile.id):
        raise AppError("LANGUAGES_REQUIRED", "Choose at least one language first.", status.HTTP_409_CONFLICT)
    if profile.availability_mode != mode:
        old = profile.availability_mode
        profile.availability_mode = mode
        record_event(
            db,
            "master.availability_changed",
            "master",
            profile.id,
            "user",
            user.id,
            {"from": old, "to": mode},
        )
    db.commit()
    return profile


def set_city(db: Session, user: User, code: str) -> MasterProfile:
    profile = own_profile(db, user, lock=True)
    places.set_master_city(db, user, profile, code)
    db.commit()
    return profile


def set_languages(db: Session, user: User, codes: list[str]) -> MasterProfile:
    """An empty list is allowed; the master then cannot stay available and is set unavailable."""
    profile = own_profile(db, user, lock=True)
    places.set_master_languages(db, user, profile, codes)
    if not codes and profile.availability_mode != "unavailable":
        profile.availability_mode = "unavailable"
    db.commit()
    return profile


def set_description(db: Session, user: User, description: str | None) -> MasterProfile:
    profile = own_profile(db, user, lock=True)
    profile.description = (description or "").strip() or None
    db.commit()
    return profile


def update_location(
    db: Session, user: User, lat: Decimal, lon: Decimal, accuracy_m: int | None
) -> MasterLocation:
    """Upsert of the single latest point; coordinates are never logged or kept as history (R-MST-07)."""
    profile = own_profile(db, user)
    if not in_latvia(float(lat), float(lon)):
        raise AppError(
            "LOCATION_OUTSIDE_AREA", "The location is outside Latvia.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    location = db.scalar(
        select(MasterLocation).where(MasterLocation.master_id == profile.id).with_for_update()
    )
    now = datetime.now(UTC)
    if location is None:
        location = MasterLocation(
            master_id=profile.id, lat=lat, lon=lon, accuracy_m=accuracy_m, updated_at=now
        )
        db.add(location)
    else:
        location.lat, location.lon, location.accuracy_m, location.updated_at = lat, lon, accuracy_m, now
    db.commit()
    return location
