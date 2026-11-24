"""Catalogue availability model (step 4.5.1, R-CAT-03): eligible-master counts and orderability, computed only
from the shared eligibility rule."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update

from app.core.business_time import business_today
from app.core.db import SessionLocal, engine
from app.models import (
    AuditLog,
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    DomainEvent,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications, specialisation_qualifications
from app.services import catalogue, eligibility
from app.services.catalogue_seed import seed_catalogue, seed_id

CATEGORY = seed_id("cm-c1")
SPEC = seed_id("cm-s01")
OTHER_SPEC = seed_id("cm-s02")
PLAIN = seed_id("cm-s01-1")
REGULATED = seed_id("cm-s01-2")  # requirement on the service
UNCONFIGURED = seed_id("cm-s01-3")  # flagged regulated, no requirement
SPEC_REQUIRED = seed_id("cm-s02-1")  # requirement on its specialisation
SERVICES = (PLAIN, REGULATED, UNCONFIGURED, SPEC_REQUIRED)
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


@dataclass
class World:
    admin_id: uuid.UUID
    electric: uuid.UUID
    gas: uuid.UUID
    today: date
    n: int = 0

    def master(
        self,
        *,
        user: str = "active",
        profile: str = "approved",
        spec: str | None = "approved",
        competencies: str | None = "verified",
        electric: date | None | str = "valid",
        gas: date | None | str = "valid",
    ) -> uuid.UUID:
        """One master; by default eligible for every service except UNCONFIGURED."""
        self.n += 1
        decided = {"decided_by": self.admin_id, "decided_at": T0}
        with SessionLocal() as db:
            account = User(
                role="master",
                email=f"m{self.n}@example.lv",
                password_hash="x",
                full_name=f"Meistars {self.n}",
                status="blocked" if user == "blocked" else "active",
                deleted_at=T0 if user == "deleted" else None,
            )
            db.add(account)
            db.flush()
            profile_row = MasterProfile(
                user_id=account.id,
                approval_status=profile,
                **(decided if profile != "pending_approval" else {}),
            )
            db.add(profile_row)
            db.flush()
            if spec:
                for spec_id in (SPEC, OTHER_SPEC):
                    db.add(
                        MasterSpecialisation(
                            master_id=profile_row.id,
                            specialisation_id=spec_id,
                            status=spec,
                            **(decided if spec in ("approved", "rejected", "revoked") else {}),
                        )
                    )
            if competencies:
                for service_id in SERVICES:
                    db.add(
                        MasterCompetency(
                            master_id=profile_row.id,
                            service_id=service_id,
                            status=competencies,
                            **(decided if competencies in ("verified", "rejected", "revoked") else {}),
                        )
                    )
            for qualification_id, held in ((self.electric, electric), (self.gas, gas)):
                if held is None:
                    continue
                if held == "revoked":
                    status, valid_until = "revoked", self.today + timedelta(days=30)
                else:
                    status = "verified"
                    valid_until = self.today + timedelta(days=30) if held == "valid" else held  # type: ignore[assignment]
                db.add(
                    MasterQualification(
                        master_id=profile_row.id,
                        qualification_id=qualification_id,
                        status=status,
                        valid_until=valid_until,
                        **decided,
                    )
                )
            db.commit()
            return profile_row.id


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    yield build_world()


def build_world() -> World:
    """Seeded catalogue with four active services: plain, regulated with a service requirement, regulated
    without any requirement (a state the API refuses; set directly to exercise the gate) and one whose
    specialisation carries the requirement."""
    with SessionLocal() as db:
        seed_catalogue(db)
        admin = User(role="admin", email="adm@example.lv", password_hash="x", full_name="Admin")
        electric = Qualification(name="Elektrodrošība", status="active")
        gas = Qualification(name="Gāzes iekārtas", status="active")
        db.add_all([admin, electric, gas])
        db.flush()
        db.execute(update(CatalogueService).where(CatalogueService.id.in_(SERVICES)).values(status="active"))
        db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == OTHER_SPEC)
            .values(status="active")
        )
        db.execute(
            update(CatalogueCategory).where(CatalogueCategory.id == seed_id("cm-c2")).values(status="active")
        )
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id == UNCONFIGURED)
            .values(qualification_required=True)
        )
        db.execute(service_qualifications.insert().values(service_id=REGULATED, qualification_id=electric.id))
        db.execute(
            specialisation_qualifications.insert().values(
                specialisation_id=OTHER_SPEC, qualification_id=gas.id
            )
        )
        db.commit()
        return World(admin.id, electric.id, gas.id, business_today(db))


def _counts(today: date | None = None) -> dict[uuid.UUID, int]:
    with SessionLocal() as db:
        return eligibility.eligible_counts(db, SERVICES, today)


def _ids(service_id: uuid.UUID, today: date | None = None) -> list[uuid.UUID]:
    with SessionLocal() as db:
        return eligibility.eligible_master_ids(db, service_id, today)


def _availability(today: date | None = None) -> dict[uuid.UUID, catalogue.Availability]:
    with SessionLocal() as db:
        return catalogue.availability(db, SERVICES, today)


def _codes(item: catalogue.Availability) -> list[str]:
    return [r.code for r in item.reasons]


# --- eligible counts ----------------------------------------------------------------------------------------


def test_counts_equal_the_shared_eligibility_rule_for_every_state(world: World) -> None:
    """Every R-MST-11 condition, alone: the count is exactly len(eligible_master_ids) for each service."""
    yesterday = world.today - timedelta(days=1)
    variants: list[dict[str, Any]] = [
        {},  # eligible everywhere it can be
        {"user": "blocked"},
        {"user": "deleted"},
        {"profile": "pending_approval"},
        {"profile": "rejected"},
        {"spec": "requested"},
        {"spec": "revoked"},
        {"spec": None},
        {"competencies": "declared"},
        {"competencies": "revoked"},
        {"competencies": None},
        {"electric": None},
        {"electric": "revoked"},
        {"electric": yesterday},  # expired
        {"electric": world.today},  # last valid day (inclusive)
        {"gas": None},
        {"gas": yesterday},
    ]
    for variant in variants:
        world.master(**variant)
    counts = _counts()
    assert set(counts) == set(SERVICES)
    for service_id in SERVICES:
        assert counts[service_id] == len(_ids(service_id)), service_id
    # Spot-check the expected values, so the rule above is not trivially equal on zeros.
    assert counts[PLAIN] == 7  # the base variant and the six that differ only in qualifications
    assert counts[REGULATED] == 4  # and electric held and valid (incl. its last day)
    assert counts[UNCONFIGURED] == 0  # regulated without a requirement admits nobody
    assert counts[SPEC_REQUIRED] == 5  # gas held and valid (electric variants do not matter here)


def test_counts_follow_the_riga_business_date(world: World) -> None:
    world.master(electric=world.today)
    assert _counts(world.today)[REGULATED] == 1
    assert _counts(world.today + timedelta(days=1))[REGULATED] == 0  # expired the next day
    assert _counts()[REGULATED] == len(_ids(REGULATED)) == 1  # default: the transaction's Riga date


def test_counts_include_every_listed_service_and_skip_unknown_ids(world: World) -> None:
    with SessionLocal() as db:
        counts = eligibility.eligible_counts(db, [PLAIN, uuid.uuid4()])
        everything = eligibility.eligible_counts(db)
        total = db.scalar(select(func.count()).select_from(CatalogueService))
    assert counts == {PLAIN: 0}
    assert len(everything) == total and set(everything.values()) == {0}


def test_counts_are_never_stored(world: World) -> None:
    master = world.master()
    assert _counts()[PLAIN] == 1
    with SessionLocal() as db:
        db.execute(
            update(MasterSpecialisation)
            .where(MasterSpecialisation.master_id == master)
            .values(status="revoked")
        )
        db.commit()
    assert _counts()[PLAIN] == 0  # the next read reflects the change at once


# --- availability -------------------------------------------------------------------------------------------


def test_orderable_when_every_condition_holds(world: World) -> None:
    world.master()
    result = _availability()
    for service_id in (PLAIN, REGULATED, SPEC_REQUIRED):
        item = result[service_id]
        assert (item.orderable, item.eligible_masters, item.reasons) == (True, 1, ())
    assert _codes(result[UNCONFIGURED]) == ["QUALIFICATION_NOT_CONFIGURED", "NO_ELIGIBLE_MASTERS"]


def test_no_eligible_master_means_not_orderable(world: World) -> None:
    world.master(profile="pending_approval")
    item = _availability()[PLAIN]
    assert (item.orderable, item.eligible_masters, _codes(item)) == (False, 0, ["NO_ELIGIBLE_MASTERS"])


@pytest.mark.parametrize("status", ["draft", "inactive", "planned", "hold", "rejected", "archived"])
def test_only_an_active_service_is_orderable(world: World, status: str) -> None:
    world.master()
    with SessionLocal() as db:
        db.execute(update(CatalogueService).where(CatalogueService.id == PLAIN).values(status=status))
        db.commit()
    item = _availability()[PLAIN]
    assert item.orderable is False and item.eligible_masters == 1  # capacity exists, the status blocks
    assert [(r.code, r.details) for r in item.reasons] == [
        ("SERVICE_NOT_ACTIVE", {"id": str(PLAIN), "status": status})
    ]
    with SessionLocal() as db:  # HOLD and the others are never activated by a read
        assert db.scalar(select(CatalogueService.status).where(CatalogueService.id == PLAIN)) == status


@pytest.mark.parametrize(
    ("model", "entity_id", "status", "code"),
    [
        (CatalogueSpecialisation, SPEC, "inactive", "SPECIALISATION_NOT_ACTIVE"),
        (CatalogueSpecialisation, SPEC, "planned", "SPECIALISATION_NOT_ACTIVE"),
        (CatalogueCategory, CATEGORY, "inactive", "CATEGORY_NOT_ACTIVE"),
        (CatalogueCategory, CATEGORY, "archived", "CATEGORY_NOT_ACTIVE"),
    ],
)
def test_the_whole_chain_must_be_active(
    world: World, model: Any, entity_id: uuid.UUID, status: str, code: str
) -> None:
    world.master()
    with SessionLocal() as db:
        db.execute(update(model).where(model.id == entity_id).values(status=status))
        db.commit()
    for service_id in (PLAIN, REGULATED):  # everything below the entity, child rows untouched
        item = _availability()[service_id]
        assert [(r.code, r.details) for r in item.reasons] == [
            (code, {"id": str(entity_id), "status": status})
        ]
        assert item.eligible_masters == 1
    assert _availability()[SPEC_REQUIRED].orderable is (code != "CATEGORY_NOT_ACTIVE")  # other specialisation


def test_regulated_gate_with_an_inactive_requirement(world: World) -> None:
    """A required type that is not `active` fails the gate (and admits nobody through eligibility)."""
    world.master()
    with SessionLocal() as db:
        db.execute(update(Qualification).where(Qualification.id == world.electric).values(status="draft"))
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id == REGULATED)
            .values(qualification_required=True)
        )
        db.commit()
    item = _availability()[REGULATED]
    assert _codes(item) == ["QUALIFICATION_NOT_CONFIGURED", "NO_ELIGIBLE_MASTERS"]
    assert item.eligible_masters == 0 == len(_ids(REGULATED))


def test_every_reason_is_reported(world: World) -> None:
    with SessionLocal() as db:
        db.execute(update(CatalogueService).where(CatalogueService.id == UNCONFIGURED).values(status="hold"))
        db.execute(
            update(CatalogueSpecialisation).where(CatalogueSpecialisation.id == SPEC).values(status="planned")
        )
        db.execute(
            update(CatalogueCategory).where(CatalogueCategory.id == CATEGORY).values(status="inactive")
        )
        db.commit()
    assert _codes(_availability()[UNCONFIGURED]) == [
        "SERVICE_NOT_ACTIVE",
        "SPECIALISATION_NOT_ACTIVE",
        "CATEGORY_NOT_ACTIVE",
        "QUALIFICATION_NOT_CONFIGURED",
        "NO_ELIGIBLE_MASTERS",
    ]


def test_availability_counts_match_eligible_counts_for_the_whole_catalogue(world: World) -> None:
    world.master()
    world.master(electric=None)
    with SessionLocal() as db:
        full = catalogue.availability(db)
        counts = eligibility.eligible_counts(db)
    assert set(full) == set(counts)
    assert {sid: item.eligible_masters for sid, item in full.items()} == counts


def test_reads_write_nothing(world: World) -> None:
    world.master()
    with SessionLocal() as db:
        before = (
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
            db.scalar(select(func.max(CatalogueService.updated_at))),
        )
    _availability()
    _counts()
    with SessionLocal() as db:
        after = (
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
            db.scalar(select(func.max(CatalogueService.updated_at))),
        )
    assert after == before


def _queries_for_availability() -> int:
    statements: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    with SessionLocal() as db:  # a fresh session: nothing preloaded
        event.listen(engine, "before_cursor_execute", count)
        try:
            catalogue.availability(db)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(statements)


def test_availability_runs_a_fixed_number_of_queries(world: World) -> None:
    """No query per service or master (no N+1), however large the catalogue or the master base."""
    small = _queries_for_availability()
    for _ in range(15):
        world.master()
    with SessionLocal() as db:
        db.execute(update(CatalogueCategory).values(status="active"))
        db.execute(update(CatalogueSpecialisation).values(status="active"))
        db.commit()
    assert _queries_for_availability() == small <= 6
