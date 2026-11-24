"""Scope, basis and locks of a proposed catalogue change (step 4.5.4.1, R-CAT-18) — PostgreSQL."""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import OperationalError

from app.core.db import SessionLocal, engine
from app.core.errors import AppError
from app.models import CatalogueCategory, CatalogueService, CatalogueSpecialisation, Qualification, User
from app.models.catalogue import service_qualifications, specialisation_qualifications
from app.services import catalogue as svc
from app.services import catalogue_impact as impact
from app.services.catalogue_impact import BasisItem, ProposedChange
from app.services.catalogue_seed import seed_catalogue, seed_id

CAT = seed_id("cm-c1")
OTHER_CAT = seed_id("cm-c2")
SPEC = seed_id("cm-s01")
SPEC_B = seed_id("cm-s02")  # same category
OTHER_SPEC = seed_id("cm-s14")  # a specialisation of category 2
SERVICE = seed_id("cm-s01-1")


@dataclass
class Fx:
    admin_id: uuid.UUID
    q_service: uuid.UUID  # required by SERVICE
    q_spec: uuid.UUID  # required by SPEC
    q_other: uuid.UUID  # required by OTHER_SPEC
    q_new: uuid.UUID  # required by nothing yet


@pytest.fixture
def fx(client: TestClient) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        admin = User(role="admin", email="adm@example.lv", password_hash="x", full_name="Admin")
        types = [Qualification(name=f"Q{n}", status="active") for n in range(4)]
        db.add_all([admin, *types])
        db.flush()
        db.execute(service_qualifications.insert().values(service_id=SERVICE, qualification_id=types[0].id))
        db.execute(
            specialisation_qualifications.insert().values(
                specialisation_id=SPEC, qualification_id=types[1].id
            )
        )
        db.execute(
            specialisation_qualifications.insert().values(
                specialisation_id=OTHER_SPEC, qualification_id=types[2].id
            )
        )
        db.commit()
        yield Fx(admin.id, types[0].id, types[1].id, types[2].id, types[3].id)


def _ids(model: Any, *where: Any) -> frozenset[uuid.UUID]:
    with SessionLocal() as db:
        return frozenset(db.scalars(select(model.id).where(*where)))


def _scope(change: ProposedChange) -> impact.Scope:
    with SessionLocal() as db:
        return impact.scope(db, change)


# --- scope per scenario -------------------------------------------------------------------------------------


def test_category_status_scope(fx: Fx) -> None:
    specs = _ids(CatalogueSpecialisation, CatalogueSpecialisation.category_id == CAT)
    services = _ids(CatalogueService, CatalogueService.specialisation_id.in_(specs))
    got = _scope(ProposedChange("category", CAT, "status", status="inactive"))
    assert got.rows == {
        "category": {CAT},
        "specialisation": specs,
        "service": services,
        "qualification": {fx.q_service, fx.q_spec},  # requirements of its services and specialisations only
    }
    assert got.modes == {
        "category": "update",
        "specialisation": "update",
        "service": "share",
        "qualification": "share",
    }
    assert got.affected_services == services and len(services) > 10


def test_specialisation_status_scope(fx: Fx) -> None:
    services = _ids(CatalogueService, CatalogueService.specialisation_id == SPEC)
    got = _scope(ProposedChange("specialisation", SPEC, "status", status="archived", reason="x"))
    assert got.rows == {
        "category": {CAT},
        "specialisation": {SPEC},
        "service": services,
        "qualification": {fx.q_service, fx.q_spec},
    }
    assert got.modes == {
        "category": "share",
        "specialisation": "update",
        "service": "share",
        "qualification": "share",
    }
    assert got.affected_services == services


def test_specialisation_move_covers_both_categories(fx: Fx) -> None:
    got = _scope(ProposedChange("specialisation", SPEC, "move", target_id=OTHER_CAT))
    assert got.rows["category"] == {CAT, OTHER_CAT}
    assert got.rows["specialisation"] == {SPEC}
    assert got.rows["service"] == _ids(CatalogueService, CatalogueService.specialisation_id == SPEC)


def test_service_move_covers_both_branches(fx: Fx) -> None:
    got = _scope(ProposedChange("service", SERVICE, "move", target_id=OTHER_SPEC))
    assert got.rows == {
        "category": {CAT, OTHER_CAT},
        "specialisation": {SPEC, OTHER_SPEC},
        "service": {SERVICE},
        "qualification": {fx.q_service, fx.q_spec, fx.q_other},  # old and new effective requirements
    }
    assert got.modes == {
        "category": "share",
        "specialisation": "share",
        "service": "update",
        "qualification": "share",
    }
    assert got.affected_services == {SERVICE}


@pytest.mark.parametrize("kind", ["status", "qualification_required", "activate_hold"])
def test_service_scope(fx: Fx, kind: str) -> None:
    got = _scope(ProposedChange("service", SERVICE, kind, status="planned", value=True))  # type: ignore[arg-type]
    assert got.rows == {
        "category": {CAT},
        "specialisation": {SPEC},
        "service": {SERVICE},
        "qualification": {fx.q_service, fx.q_spec},
    }


def test_requirements_scope_has_old_and_new_types(fx: Fx) -> None:
    """Removing one type and adding another: both are in the scope (and locked)."""
    service = _scope(ProposedChange("service", SERVICE, "requirements", qualification_ids=(fx.q_new,)))
    assert service.rows["qualification"] == {fx.q_service, fx.q_spec, fx.q_new}
    spec = _scope(ProposedChange("specialisation", SPEC, "requirements", qualification_ids=(fx.q_new,)))
    assert spec.rows["qualification"] == {fx.q_service, fx.q_spec, fx.q_new}
    flag = _scope(ProposedChange("specialisation", SPEC, "qualification_required", value=True))
    assert flag.rows["service"] == _ids(CatalogueService, CatalogueService.specialisation_id == SPEC)


@pytest.mark.parametrize(
    ("entity", "kind"),
    [
        ("category", "move"),
        ("category", "requirements"),
        ("specialisation", "activate_hold"),
        ("category", "activate_hold"),
    ],
)
def test_unsupported_changes(fx: Fx, entity: str, kind: str) -> None:
    with pytest.raises(AppError) as exc:
        _scope(ProposedChange(entity, uuid.uuid4(), kind))  # type: ignore[arg-type]
    assert (exc.value.code, exc.value.status_code) == ("IMPACT_CHANGE_NOT_SUPPORTED", 422)


@pytest.mark.parametrize("entity", ["category", "specialisation", "service"])
def test_unknown_entry(fx: Fx, entity: str) -> None:
    with pytest.raises(AppError) as exc:
        _scope(ProposedChange(entity, uuid.uuid4(), "status", status="inactive"))  # type: ignore[arg-type]
    assert (exc.value.code, exc.value.status_code) == (f"{entity.upper()}_NOT_FOUND", 404)


# --- basis ------------------------------------------------------------------------------------------------


def test_basis_is_every_scope_row_with_its_version(fx: Fx) -> None:
    with SessionLocal() as db:
        db.execute(update(CatalogueService).where(CatalogueService.id == SERVICE).values(version=7))
        db.commit()
    with SessionLocal() as db:
        current, basis = impact.lock_and_read_basis(
            db, ProposedChange("specialisation", SPEC, "status", status="planned")
        )
        db.rollback()
    expected = {(k, i) for k, ids in current.rows.items() for i in ids}
    assert {(b.kind, b.id) for b in basis} == expected and basis == sorted(basis)
    assert BasisItem("service", SERVICE, 7) in basis
    assert BasisItem("specialisation", SPEC, 1) in basis


def test_difference_reports_changed_added_and_removed() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    then = [BasisItem("service", a, 1), BasisItem("service", b, 1)]
    now = [BasisItem("service", a, 2), BasisItem("service", c, 1)]
    assert impact.difference(now, then) == {
        "changed": [{"kind": "service", "id": str(a), "expected": 1, "current": 2}],
        "added": [{"kind": "service", "id": str(c), "version": 1}],
        "removed": [{"kind": "service", "id": str(b), "expected": 1}],
    }
    assert impact.difference(then, then) == {"changed": [], "added": [], "removed": []}


# --- what the locks block (PostgreSQL) ---------------------------------------------------------------------


def _blocked(statement: Callable[[Any], None]) -> bool:
    """True if `statement` cannot get its lock within 300 ms while the scope is locked elsewhere."""
    with SessionLocal() as other:
        other.execute(text("SET LOCAL lock_timeout = '300ms'"))
        try:
            statement(other)
            other.flush()
            other.rollback()
            return False
        except OperationalError:
            other.rollback()
            return True


def _while_locked(change: ProposedChange, statement: Callable[[Any], None]) -> bool:
    result: list[bool] = []
    with SessionLocal() as db:
        impact.lock_and_read_basis(db, change)
        thread = threading.Thread(target=lambda: result.append(_blocked(statement)))
        thread.start()
        thread.join(timeout=10)
        db.rollback()
    return result[0]


def _new_service(spec_id: uuid.UUID) -> Callable[[Any], None]:
    def run(db: Any) -> None:
        db.execute(
            text(
                "INSERT INTO catalogue_services "
                "(id, specialisation_id, name, w_id, status, source, sort_order) "
                "VALUES (:id, :spec, :name, 'W990', 'inactive', 'admin', 99)"
            ),
            {"id": uuid.uuid4(), "spec": spec_id, "name": f"Jauns {uuid.uuid4()}"},
        )

    return run


def _new_specialisation(category_id: uuid.UUID) -> Callable[[Any], None]:
    def run(db: Any) -> None:
        db.execute(
            text(
                "INSERT INTO catalogue_specialisations (id, category_id, name, status, source, sort_order) "
                "VALUES (:id, :cat, :name, 'inactive', 'admin', 99)"
            ),
            {"id": uuid.uuid4(), "cat": category_id, "name": f"Jauna {uuid.uuid4()}"},
        )

    return run


def _move_service(service_id: uuid.UUID, target: uuid.UUID) -> Callable[[Any], None]:
    def run(db: Any) -> None:
        db.execute(text("SELECT 1 FROM catalogue_specialisations WHERE id = :t FOR SHARE"), {"t": target})
        db.execute(text("SELECT 1 FROM catalogue_services WHERE id = :s FOR UPDATE"), {"s": service_id})
        db.execute(
            update(CatalogueService).where(CatalogueService.id == service_id).values(specialisation_id=target)
        )

    return run


def _set(model: Any, row_id: uuid.UUID, **values: Any) -> Callable[[Any], None]:
    def run(db: Any) -> None:
        db.execute(update(model).where(model.id == row_id).values(**values))

    return run


CATEGORY_CHANGE = ProposedChange("category", CAT, "status", status="inactive")
SPEC_CHANGE = ProposedChange("specialisation", SPEC, "status", status="planned")
SERVICE_CHANGE = ProposedChange("service", SERVICE, "status", status="planned")


@pytest.mark.parametrize(
    ("change", "name", "statement", "blocked"),
    [
        # A changed container: nothing joins or leaves it while the change is checked and applied.
        (CATEGORY_CHANGE, "new service in an affected specialisation", lambda fx: _new_service(SPEC), True),
        (CATEGORY_CHANGE, "new specialisation in the category", lambda fx: _new_specialisation(CAT), True),
        (SPEC_CHANGE, "new service in the specialisation", lambda fx: _new_service(SPEC), True),
        (
            SPEC_CHANGE,
            "service moved into the branch",
            lambda fx: _move_service(seed_id("cm-s02-1"), SPEC),
            True,
        ),
        (SPEC_CHANGE, "service moved out of the branch", lambda fx: _move_service(SERVICE, OTHER_SPEC), True),
        (
            CATEGORY_CHANGE,
            "specialisation moved out",
            lambda fx: _set(CatalogueSpecialisation, SPEC, category_id=OTHER_CAT),
            True,
        ),
        # Every row of the scope is protected against changes.
        (
            SPEC_CHANGE,
            "parent category changed",
            lambda fx: _set(CatalogueCategory, CAT, status="planned"),
            True,
        ),
        (
            SPEC_CHANGE,
            "child service changed",
            lambda fx: _set(CatalogueService, SERVICE, review_note="x"),
            True,
        ),
        (
            SERVICE_CHANGE,
            "required type archived",
            lambda fx: _set(Qualification, fx.q_spec, status="archived"),
            True,
        ),
        # Rows outside the scope stay free.
        (
            SERVICE_CHANGE,
            "sibling service changed",
            lambda fx: _set(CatalogueService, seed_id("cm-s01-2"), review_note="x"),
            False,
        ),
        (SERVICE_CHANGE, "new sibling service", lambda fx: _new_service(SPEC), False),
        (
            SPEC_CHANGE,
            "other specialisation changed",
            lambda fx: _set(CatalogueSpecialisation, SPEC_B, description="x"),
            False,
        ),
        (
            SPEC_CHANGE,
            "unrelated type archived",
            lambda fx: _set(Qualification, fx.q_other, status="archived"),
            False,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_locks_freeze_exactly_the_scope(
    fx: Fx, change: ProposedChange, name: str, statement: Callable[[Fx], Callable[[Any], None]], blocked: bool
) -> None:
    assert _while_locked(change, statement(fx)) is blocked, name


def test_busy_catalogue_is_reported(fx: Fx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(impact, "LOCK_TIMEOUT", "200ms")
    with SessionLocal() as holder:
        holder.execute(text("SELECT 1 FROM catalogue_services WHERE id = :s FOR UPDATE"), {"s": SERVICE})
        with SessionLocal() as db, pytest.raises(AppError) as exc:
            impact.lock_and_read_basis(db, SPEC_CHANGE)
        holder.rollback()
    assert (exc.value.code, exc.value.status_code) == ("CATALOGUE_BUSY", 409)


def test_scope_changed_while_waiting_for_the_locks(fx: Fx) -> None:
    """A specialisation is added to the category between the first read and the locks: refused, not missed."""
    outcome: list[Any] = []
    new_spec = uuid.uuid4()
    with SessionLocal() as holder:
        holder.execute(text("SELECT 1 FROM catalogue_categories WHERE id = :c FOR UPDATE"), {"c": CAT})
        holder.execute(
            text(
                "INSERT INTO catalogue_specialisations (id, category_id, name, status, source, sort_order) "
                "VALUES (:id, :cat, 'Pievienota', 'inactive', 'admin', 99)"
            ),
            {"id": new_spec, "cat": CAT},
        )

        def attempt() -> None:
            with SessionLocal() as db:
                try:
                    impact.lock_and_read_basis(db, CATEGORY_CHANGE)
                    outcome.append("ok")
                except AppError as exc:
                    outcome.append(exc)
                db.rollback()

        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive()  # waits for the category lock
        holder.commit()
    thread.join(timeout=30)
    [error] = outcome
    assert isinstance(error, AppError) and error.code == "IMPACT_PREVIEW_OUTDATED"
    assert {"kind": "specialisation", "id": str(new_spec)} in error.details["added"]


def test_prepared_change_after_the_scope_locks_never_upgrades(fx: Fx) -> None:
    """Every prepare_* takes rows the scope already holds, in the same or a weaker mode: two transactions
    running scope locks + prepare on overlapping branches never deadlock."""

    def service_change() -> str:
        with SessionLocal() as db:
            admin = db.get(User, fx.admin_id)
            try:
                impact.lock_and_read_basis(db, SERVICE_CHANGE)
                svc.prepare_service_status(db, admin, SERVICE, "planned", None, 1)
                db.rollback()
                return "ok"
            except Exception as exc:  # noqa: BLE001 - reported
                db.rollback()
                return type(exc).__name__

    def specialisation_change() -> str:
        with SessionLocal() as db:
            admin = db.get(User, fx.admin_id)
            version = db.scalar(
                select(CatalogueSpecialisation.version).where(CatalogueSpecialisation.id == SPEC)
            )
            try:
                impact.lock_and_read_basis(db, SPEC_CHANGE)
                svc.prepare_specialisation_status(db, admin, SPEC, "planned", None, version)
                db.rollback()
                return "ok"
            except Exception as exc:  # noqa: BLE001 - reported
                db.rollback()
                return type(exc).__name__

    for _ in range(10):
        barrier = threading.Barrier(4)
        results: list[str] = []

        def run(job: Callable[[], str], barrier: threading.Barrier, results: list[str]) -> None:
            barrier.wait()
            results.append(job())

        jobs = [service_change, specialisation_change, service_change, specialisation_change]
        threads = [threading.Thread(target=run, args=(job, barrier, results)) for job in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert results == ["ok"] * 4, results


# --- performance --------------------------------------------------------------------------------------------


def _queries(change: ProposedChange) -> int:
    statements: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    with SessionLocal() as db:
        event.listen(engine, "before_cursor_execute", count)
        try:
            impact.lock_and_read_basis(db, change)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        db.rollback()
    return len(statements)


def test_fixed_number_of_queries_whatever_the_branch_size(fx: Fx) -> None:
    small = _queries(CATEGORY_CHANGE)
    with (
        SessionLocal() as db
    ):  # grow the branch: every service of category 2 moves under SPEC, all with types
        db.execute(
            update(CatalogueService)
            .where(
                CatalogueService.specialisation_id.in_(
                    _ids(CatalogueSpecialisation, CatalogueSpecialisation.category_id == OTHER_CAT)
                )
            )
            .values(specialisation_id=SPEC)
        )
        db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == SPEC_B)
            .values(description="x")
        )
        db.commit()
    assert len(_ids(CatalogueService, CatalogueService.specialisation_id == SPEC)) > 20  # was 4
    assert _queries(CATEGORY_CHANGE) == small <= 16
