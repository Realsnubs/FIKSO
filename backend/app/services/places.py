"""Cities and communication languages (reference data) and the master's work city / languages."""

from typing import Any

from fastapi import status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.integrations.maps import distance_km
from app.models import City, CommunicationLanguage, MasterCity, MasterLanguage, MasterProfile, User
from app.services.events import record_event

ANY_LANGUAGE = "any"
MAX_LANGUAGES = 24


def cities(db: Session) -> list[City]:
    return list(db.scalars(select(City).where(City.active).order_by(City.sort_order, City.name_lv)))


def languages(db: Session) -> list[CommunicationLanguage]:
    query = select(CommunicationLanguage).where(CommunicationLanguage.active)
    return list(db.scalars(query.order_by(CommunicationLanguage.sort_order)))


def city_out(city: City) -> dict[str, Any]:
    return {"code": city.code, "name": {"lv": city.name_lv, "en": city.name_en, "ru": city.name_ru}}


def language_out(language: CommunicationLanguage) -> dict[str, Any]:
    return {
        "code": language.code,
        "name": {"lv": language.name_lv, "en": language.name_en, "ru": language.name_ru},
        "native_name": language.native_name,
        "flag": language.flag,
    }


def get_city(db: Session, code: str) -> City:
    city = db.get(City, code.strip().lower())
    if city is None or not city.active:
        raise AppError("UNKNOWN_CITY", "Choose a city from the list.", status.HTTP_422_UNPROCESSABLE_CONTENT)
    return city


def check_language(db: Session, code: str | None) -> str | None:
    """`any`/None → None (any language); a known active code → the code; anything else is refused."""
    if code is None or code == ANY_LANGUAGE:
        return None
    language = db.get(CommunicationLanguage, code.strip().lower())
    if language is None or not language.active:
        raise AppError(
            "UNKNOWN_LANGUAGE", "Choose a language from the list.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    return language.code


def point_in_city(city: City, lat: float, lon: float) -> bool:
    """Plausibility of a request point for the chosen city (technical check, not a business radius)."""
    return distance_km(float(city.lat), float(city.lon), lat, lon) <= float(city.max_distance_km)


def master_city_code(db: Session, master_id: Any) -> str | None:
    return db.scalar(
        select(MasterCity.city_code).where(MasterCity.master_id == master_id, MasterCity.is_primary.is_(True))
    )


def master_language_codes(db: Session, master_id: Any) -> list[str]:
    rows = db.scalars(select(MasterLanguage.language_code).where(MasterLanguage.master_id == master_id))
    return sorted(rows)


def set_master_city(db: Session, user: User, profile: MasterProfile, code: str) -> None:
    """One primary city for now; the table already supports more cities per master later."""
    city = get_city(db, code)
    db.execute(delete(MasterCity).where(MasterCity.master_id == profile.id))
    db.flush()
    db.add(MasterCity(master_id=profile.id, city_code=city.code, is_primary=True))
    record_event(db, "master.work_city_changed", "master", profile.id, "user", user.id, {"city": city.code})


def set_master_languages(db: Session, user: User, profile: MasterProfile, codes: list[str]) -> None:
    wanted = {c.strip().lower() for c in codes if c.strip()}
    if len(wanted) > MAX_LANGUAGES:
        raise AppError("TOO_MANY_LANGUAGES", "Too many languages.", status.HTTP_422_UNPROCESSABLE_CONTENT)
    known = set(db.scalars(select(CommunicationLanguage.code).where(CommunicationLanguage.active)))
    unknown = sorted(wanted - known)
    if unknown:
        raise AppError(
            "UNKNOWN_LANGUAGE",
            "Choose languages from the list.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"codes": unknown},
        )
    db.execute(delete(MasterLanguage).where(MasterLanguage.master_id == profile.id))
    db.flush()
    for code in sorted(wanted):
        db.add(MasterLanguage(master_id=profile.id, language_code=code))
    payload = {"languages": sorted(wanted)}
    record_event(db, "master.languages_changed", "master", profile.id, "user", user.id, payload)
