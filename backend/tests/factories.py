"""Small builders for Stage C/D tests: an orderable catalogue and eligible, logged-in masters."""

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    MasterCity,
    MasterCompetency,
    MasterLanguage,
    MasterLocation,
    MasterProfile,
    MasterSpecialisation,
    User,
)
from tests.conftest import PASSWORD, auth

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
RIGA = (Decimal("56.949600"), Decimal("24.105200"))
_n = itertools.count(1)


@dataclass
class Catalogue:
    category: uuid.UUID
    spec: uuid.UUID
    service: uuid.UUID
    w_id: str
    other_service: uuid.UUID
    planned_spec: uuid.UUID
    draft_service: uuid.UUID
    admin_id: uuid.UUID = field(default_factory=uuid.uuid4)


def build_catalogue() -> Catalogue:
    with SessionLocal() as db:
        admin = User(role="admin", email=f"sys{next(_n)}@example.lv", password_hash="x", full_name="Sys")
        db.add(admin)
        db.flush()
        cat = CatalogueCategory(name="Mazā santehnika", status="active")
        db.add(cat)
        db.flush()
        spec = CatalogueSpecialisation(name="Gaismekļu meistars", status="active", category_id=cat.id)
        planned = CatalogueSpecialisation(name="Logu meistars", status="planned", category_id=cat.id)
        db.add_all([spec, planned])
        db.flush()
        service = CatalogueService(
            name="Gaismekļa uzstādīšana", status="active", specialisation_id=spec.id, w_id="W092"
        )
        other = CatalogueService(
            name="Lustras nomaiņa", status="active", specialisation_id=spec.id, w_id="W093"
        )
        draft = CatalogueService(
            name="Prožektora montāža", status="draft", specialisation_id=spec.id, w_id="W094"
        )
        db.add_all([service, other, draft])
        db.commit()
        return Catalogue(cat.id, spec.id, service.id, "W092", other.id, planned.id, draft.id, admin.id)


@dataclass
class Master:
    user_id: uuid.UUID
    profile_id: uuid.UUID
    token: str
    email: str


def make_master(
    client: TestClient,
    cat: Catalogue,
    *,
    services: tuple[uuid.UUID, ...] | None = None,
    mode: str = "available_now",
    location: tuple[Decimal, Decimal] | None = RIGA,
    location_at: datetime | None = None,
    city: str | None = "riga",
    languages: tuple[str, ...] = ("lv", "ru"),
    rating: Decimal | None = None,
    completed: int = 0,
) -> Master:
    n = next(_n)
    email = f"meistars{n}@example.lv"
    with SessionLocal() as db:
        user = User(
            role="master",
            email=email,
            phone=f"+37166{n:06d}",
            password_hash=hash_password(PASSWORD),
            full_name=f"Meistars {n}",
        )
        db.add(user)
        db.flush()
        profile = MasterProfile(
            user_id=user.id,
            approval_status="approved",
            decided_by=cat.admin_id,
            decided_at=T0,
            availability_mode=mode,
            rating_avg=rating,
            rating_count=1 if rating else 0,
            completed_jobs=completed,
        )
        db.add(profile)
        db.flush()
        db.add(
            MasterSpecialisation(
                master_id=profile.id,
                specialisation_id=cat.spec,
                status="approved",
                decided_by=cat.admin_id,
                decided_at=T0,
            )
        )
        for service_id in services or (cat.service, cat.other_service):
            db.add(
                MasterCompetency(
                    master_id=profile.id,
                    service_id=service_id,
                    status="verified",
                    decided_by=cat.admin_id,
                    decided_at=T0,
                )
            )
        if city is not None:
            db.add(MasterCity(master_id=profile.id, city_code=city, is_primary=True))
        for code in languages:
            db.add(MasterLanguage(master_id=profile.id, language_code=code))
        if location is not None:
            db.add(
                MasterLocation(
                    master_id=profile.id,
                    lat=location[0],
                    lon=location[1],
                    updated_at=location_at or datetime.now(UTC),
                )
            )
        db.commit()
        ids = (user.id, profile.id)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return Master(ids[0], ids[1], resp.json()["access_token"], email)


def login_client(client: TestClient, register_fn: object) -> tuple[str, uuid.UUID]:
    body = register_fn(client, "client")  # type: ignore[operator]
    return body["access_token"], uuid.UUID(body["user"]["id"])


__all__ = ["auth"]
