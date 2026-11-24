"""Impact preview POST /api/v1/admin/catalogue/impact (step 4.5.4.2, R-CAT-18) — PostgreSQL."""

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update

from app.core.db import SessionLocal, engine
from app.models import (
    AuditLog,
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    DomainEvent,
    MasterProfile,
    Qualification,
    User,
)
from app.models.catalogue import service_qualifications, specialisation_qualifications
from app.services import catalogue as svc
from app.services import catalogue_impact
from app.services.catalogue_seed import seed_id
from tests.conftest import auth, register
from tests.test_catalogue_availability import (
    CATEGORY,
    OTHER_SPEC,
    PLAIN,
    REGULATED,
    SPEC,
    UNCONFIGURED,
    World,
    build_world,
)

URL = "/api/v1/admin/catalogue/impact"
BASE = "/api/v1/admin/catalogue"
PLANNED_CATEGORY = seed_id("cm-c3")


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    world = build_world()
    with SessionLocal() as db:  # a state the API allows, so specialisation-level changes pass the gate
        db.execute(
            update(CatalogueService).where(CatalogueService.id == UNCONFIGURED).values(status="inactive")
        )
        db.commit()
    yield world


@pytest.fixture
def admin(world: World, admin_token: str) -> dict[str, str]:
    return auth(admin_token)


def _masters(world: World) -> dict[str, uuid.UUID]:
    """Full (eligible everywhere it can be), without electric, without gas."""
    return {
        "full": world.master(),
        "no_electric": world.master(electric=None),
        "no_gas": world.master(gas=None),
    }


def _preview(
    client: TestClient, admin: dict[str, str], entity: str, entity_id: Any, change: dict[str, Any]
) -> Any:
    return client.post(URL, json={"entity": entity, "id": str(entity_id), "change": change}, headers=admin)


def _state() -> tuple[Any, ...]:
    """Every catalogue and master row plus all requirement links, audit entries and events."""
    with SessionLocal() as db:
        rows = [
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (
                CatalogueCategory,
                CatalogueSpecialisation,
                CatalogueService,
                Qualification,
                MasterProfile,
            )
            for row in db.scalars(select(model))
        ]
        links = [
            tuple(r)
            for t in (service_qualifications, specialisation_qualifications)
            for r in db.execute(select(t))
        ]
        return (
            sorted(rows, key=repr),
            sorted(links, key=repr),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _tree_services(client: TestClient, admin: dict[str, str]) -> dict[str, dict[str, Any]]:
    body = client.get(f"{BASE}/tree", headers=admin).json()
    return {s["id"]: s for c in body["categories"] for sp in c["specialisations"] for s in sp["services"]}


def _version(body: dict[str, Any], kind: str, entity_id: Any) -> int:
    return int(next(b["version"] for b in body["basis"] if b["kind"] == kind and b["id"] == str(entity_id)))


# The 10 agreed kinds of change: (entity, id, change, the real request as (method, path, body)).
CASES: dict[str, tuple[str, uuid.UUID, dict[str, Any], tuple[str, str, dict[str, Any]]]] = {
    "category_status": (
        "category",
        CATEGORY,
        {"kind": "status", "status": "inactive"},
        ("post", f"/categories/{CATEGORY}/status", {"status": "inactive"}),
    ),
    "specialisation_status": (
        "specialisation",
        SPEC,
        {"kind": "status", "status": "planned"},
        ("post", f"/specialisations/{SPEC}/status", {"status": "planned"}),
    ),
    "specialisation_move": (
        "specialisation",
        SPEC,
        {"kind": "move", "target_id": str(PLANNED_CATEGORY)},
        ("patch", f"/specialisations/{SPEC}", {"category_id": str(PLANNED_CATEGORY)}),
    ),
    "specialisation_flag": (
        "specialisation",
        OTHER_SPEC,
        {"kind": "qualification_required", "value": True},
        ("patch", f"/specialisations/{OTHER_SPEC}", {"qualification_required": True}),
    ),
    "specialisation_requirements": (
        "specialisation",
        SPEC,
        {"kind": "requirements", "qualification_ids": ["E"]},
        ("put", f"/specialisations/{SPEC}/qualifications", {"qualification_ids": ["E"]}),
    ),
    "service_status": (
        "service",
        PLAIN,
        {"kind": "status", "status": "inactive"},
        ("post", f"/services/{PLAIN}/status", {"status": "inactive"}),
    ),
    "service_move": (
        "service",
        PLAIN,
        {"kind": "move", "target_id": str(OTHER_SPEC)},
        ("patch", f"/services/{PLAIN}", {"specialisation_id": str(OTHER_SPEC)}),
    ),
    "service_flag": (
        "service",
        REGULATED,
        {"kind": "qualification_required", "value": True},
        ("patch", f"/services/{REGULATED}", {"qualification_required": True}),
    ),
    "service_requirements": (
        "service",
        REGULATED,
        {"kind": "requirements", "qualification_ids": ["G"]},
        ("put", f"/services/{REGULATED}/qualifications", {"qualification_ids": ["G"]}),
    ),
    "activate_hold": (
        "service",
        PLAIN,
        {"kind": "activate_hold", "reason": "Pārbaudīts"},
        ("post", f"/services/{PLAIN}/activate-hold", {"confirm": True, "reason": "Pārbaudīts"}),
    ),
}


def _resolve(value: Any, world: World) -> Any:
    """Placeholders: "E"/"G" = the electric/gas qualification IDs."""
    if isinstance(value, dict):
        return {k: _resolve(v, world) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, world) for v in value]
    return (
        {"E": str(world.electric), "G": str(world.gas)}.get(value, value) if isinstance(value, str) else value
    )


@pytest.mark.parametrize("name", CASES)
def test_preview_matches_the_real_change(
    client: TestClient, admin: dict[str, str], world: World, name: str
) -> None:
    entity, entity_id, change, (method, path, body) = CASES[name]
    _masters(world)
    if name == "activate_hold":
        with SessionLocal() as db:
            db.execute(update(CatalogueService).where(CatalogueService.id == PLAIN).values(status="hold"))
            db.commit()
    tree_before = _tree_services(client, admin)
    before = _state()
    resp = _preview(client, admin, entity, entity_id, _resolve(change, world))
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert _state() == before  # nothing written, logged or announced

    # "before" is today's tree; then the real change, with the version from the basis, gives exactly "after".
    for item in preview["services"]:
        current = tree_before[item["service_id"]]
        assert item["before"] == {k: current[f] for k, f in _FIELDS.items()}, (name, item["w_id"])
    payload = _resolve(body, world) | {"expected_version": _version(preview, entity, entity_id)}
    real = getattr(client, method)(f"{BASE}{path}", json=payload, headers=admin)
    assert real.status_code == 200, real.text
    tree_after = _tree_services(client, admin)
    for item in preview["services"]:
        current = tree_after[item["service_id"]]
        assert item["after"] == {k: current[f] for k, f in _FIELDS.items()}, (name, item["w_id"])
    stops = {s for s in tree_before if tree_before[s]["orderable"] and not tree_after[s]["orderable"]}
    starts = {s for s in tree_before if not tree_before[s]["orderable"] and tree_after[s]["orderable"]}
    assert set(preview["stops_being_orderable"]) == stops
    assert set(preview["becomes_orderable"]) == starts


_FIELDS = {"orderable": "orderable", "eligible_masters": "eligible_masters", "reasons": "orderable_reasons"}


def test_affected_services_and_basis(client: TestClient, admin: dict[str, str], world: World) -> None:
    body = _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"}).json()
    with SessionLocal() as db:
        specs = set(
            db.scalars(
                select(CatalogueSpecialisation.id).where(CatalogueSpecialisation.category_id == CATEGORY)
            )
        )
        services = set(
            db.scalars(select(CatalogueService.id).where(CatalogueService.specialisation_id.in_(specs)))
        )
        versions = {
            (kind, row_id): version
            for kind, model in (
                ("category", CatalogueCategory),
                ("specialisation", CatalogueSpecialisation),
                ("service", CatalogueService),
            )
            for row_id, version in db.execute(select(model.id, model.version))
        }
    assert {uuid.UUID(s["service_id"]) for s in body["services"]} == services
    kinds = {(b["kind"], uuid.UUID(b["id"])) for b in body["basis"]}
    assert {("category", CATEGORY)} | {("specialisation", s) for s in specs} | {
        ("service", s) for s in services
    } <= kinds
    assert ("qualification", world.electric) in kinds  # required by REGULATED in the branch
    for b in body["basis"]:
        if b["kind"] != "qualification":
            assert versions[(b["kind"], uuid.UUID(b["id"]))] == b["version"]
    assert body["entity"] == "category" and body["change"] == {
        "kind": "status",
        "status": "inactive",
        "reason": None,
    }


def test_masters_summary(client: TestClient, admin: dict[str, str], world: World) -> None:
    masters = _masters(world)
    body = _preview(
        client,
        admin,
        "specialisation",
        SPEC,
        {"kind": "requirements", "qualification_ids": [str(world.electric)]},
    ).json()
    summary = body["masters"]
    assert summary["by_specialisation_status"] == {"approved": 3}
    assert summary["by_competency_status"] == {"verified": 9}  # 3 masters × 3 services of SPEC
    losing = summary["losing_eligibility"]
    assert losing["total"] == 1 and [i["master_id"] for i in losing["items"]] == [str(masters["no_electric"])]
    assert set(losing["items"][0]) == {"master_id", "full_name"}


def test_notes_open_requests_and_snapshot(client: TestClient, admin: dict[str, str], world: World) -> None:
    body = _preview(client, admin, "service", PLAIN, {"kind": "status", "status": "inactive"}).json()
    assert body["open_requests"] is None
    assert "step 5" in body["notes"]["open_requests"]
    assert "snapshot" in body["notes"]["eligible_masters"] and body["computed_at"]


def test_losing_list_is_capped_at_100_without_contacts(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    for _ in range(105):
        world.master(electric=None)
    body = _preview(
        client,
        admin,
        "specialisation",
        SPEC,
        {"kind": "requirements", "qualification_ids": [str(world.electric)]},
    ).json()
    losing = body["masters"]["losing_eligibility"]
    assert losing["total"] == 105 and len(losing["items"]) == 100
    names = [i["full_name"] for i in losing["items"]]
    assert names == sorted(names)
    with SessionLocal() as db:
        emails = list(db.scalars(select(User.email).where(User.role == "master")))
    response = str(body)
    assert (
        not any(email in response for email in emails) and "phone" not in response and "email" not in response
    )


# --- invalid changes: the same errors as the real operation -------------------------------------------------


INVALID: dict[str, tuple[str, uuid.UUID, dict[str, Any], tuple[str, str, dict[str, Any]], int, str]] = {
    "transition": (
        "service",
        PLAIN,
        {"kind": "status", "status": "draft"},
        ("post", f"/services/{PLAIN}/status", {"status": "draft"}),
        409,
        "INVALID_STATUS_TRANSITION",
    ),
    "reason_required": (
        "specialisation",
        SPEC,
        {"kind": "status", "status": "archived"},
        ("post", f"/specialisations/{SPEC}/status", {"status": "archived"}),
        422,
        "REASON_REQUIRED",
    ),
    "gate": (
        "specialisation",
        SPEC,
        {"kind": "qualification_required", "value": True},
        ("patch", f"/specialisations/{SPEC}", {"qualification_required": True}),
        409,
        "QUALIFICATION_NOT_CONFIGURED",
    ),
    "not_on_hold": (
        "service",
        PLAIN,
        {"kind": "activate_hold", "reason": "Pārbaudīts"},
        ("post", f"/services/{PLAIN}/activate-hold", {"confirm": True, "reason": "Pārbaudīts"}),
        409,
        "NOT_ON_HOLD",
    ),
    "hold_through_status": (
        "service",
        PLAIN,
        {"kind": "status", "status": "active"},
        ("post", f"/services/{PLAIN}/status", {"status": "active"}),
        409,
        "HOLD_ACTIVATION_REQUIRED",
    ),
    "unknown_type": (
        "service",
        PLAIN,
        {"kind": "requirements", "qualification_ids": [str(uuid.UUID(int=7))]},
        ("put", f"/services/{PLAIN}/qualifications", {"qualification_ids": [str(uuid.UUID(int=7))]}),
        404,
        "QUALIFICATION_NOT_FOUND",
    ),
    "unknown_target": (
        "service",
        PLAIN,
        {"kind": "move", "target_id": str(uuid.UUID(int=9))},
        ("patch", f"/services/{PLAIN}", {"specialisation_id": str(uuid.UUID(int=9))}),
        404,
        "SPECIALISATION_NOT_FOUND",
    ),
}


@pytest.mark.parametrize("name", INVALID)
def test_invalid_change_gives_the_real_error(
    client: TestClient, admin: dict[str, str], world: World, name: str
) -> None:
    entity, entity_id, change, (method, path, body), code, error = INVALID[name]
    if name == "hold_through_status":
        with SessionLocal() as db:
            db.execute(update(CatalogueService).where(CatalogueService.id == PLAIN).values(status="hold"))
            db.commit()
    before = _state()
    previewed = _preview(client, admin, entity, entity_id, change)
    model = {
        "category": CatalogueCategory,
        "specialisation": CatalogueSpecialisation,
        "service": CatalogueService,
    }[entity]
    with SessionLocal() as db:
        version = db.scalar(select(model.version).where(model.id == entity_id))
    real = getattr(client, method)(f"{BASE}{path}", json=body | {"expected_version": version}, headers=admin)
    assert (previewed.status_code, previewed.json()["error"]["code"]) == (code, error)
    assert (real.status_code, real.json()["error"]["code"]) == (code, error)
    assert _state() == before


@pytest.mark.parametrize(
    ("entity", "kind"),
    [("category", "move"), ("category", "requirements"), ("specialisation", "activate_hold")],
)
def test_unsupported_kind(client: TestClient, admin: dict[str, str], entity: str, kind: str) -> None:
    change = {
        "move": {"kind": "move", "target_id": str(SPEC)},
        "requirements": {"kind": "requirements", "qualification_ids": []},
        "activate_hold": {"kind": "activate_hold", "reason": "Iemesls"},
    }[kind]
    resp = _preview(client, admin, entity, CATEGORY if entity == "category" else SPEC, change)
    assert (resp.status_code, resp.json()["error"]["code"]) == (422, "IMPACT_CHANGE_NOT_SUPPORTED")


@pytest.mark.parametrize("entity", ["category", "specialisation", "service"])
def test_unknown_entity(client: TestClient, admin: dict[str, str], entity: str) -> None:
    resp = _preview(client, admin, entity, uuid.uuid4(), {"kind": "status", "status": "inactive"})
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, f"{entity.upper()}_NOT_FOUND")


@pytest.mark.parametrize(
    "body",
    [
        {"entity": "service", "id": str(PLAIN)},
        {"entity": "service", "id": str(PLAIN), "change": {"kind": "status"}},
        {"entity": "service", "id": str(PLAIN), "change": {"kind": "rename", "name": "x"}},
        {"entity": "master", "id": str(PLAIN), "change": {"kind": "status", "status": "inactive"}},
        {"entity": "service", "id": "x", "change": {"kind": "status", "status": "inactive"}},
        {"entity": "service", "id": str(PLAIN), "change": {"kind": "activate_hold"}},
        {"entity": "service", "id": str(PLAIN), "change": {"kind": "status", "status": "inactive"}, "x": 1},
        {
            "entity": "service",
            "id": str(PLAIN),
            "change": {"kind": "requirements", "qualification_ids": ["x"] * 2001},
        },
    ],
)
def test_malformed_requests(client: TestClient, admin: dict[str, str], body: dict[str, Any]) -> None:
    assert client.post(URL, json=body, headers=admin).status_code == 422


def test_only_admins(client: TestClient, world: World) -> None:
    body = {"entity": "service", "id": str(PLAIN), "change": {"kind": "status", "status": "inactive"}}
    assert client.post(URL, json=body).status_code == 401
    for role in ("master", "client"):
        resp = client.post(URL, json=body, headers=auth(register(client, role)["access_token"]))
        assert resp.status_code == 403 and "services" not in resp.text


# --- transactions and locks (PostgreSQL) --------------------------------------------------------------------


def test_locks_are_released_after_the_preview(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    assert (
        _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"}).status_code
        == 200
    )
    with SessionLocal() as other:
        other.execute(text("SET LOCAL lock_timeout = '300ms'"))
        other.execute(
            update(CatalogueCategory).where(CatalogueCategory.id == CATEGORY).values(description="x")
        )
        other.execute(update(CatalogueService).where(CatalogueService.id == PLAIN).values(review_note="x"))
        other.rollback()  # reached without OperationalError: nothing is still locked


def test_busy_catalogue(
    client: TestClient, admin: dict[str, str], world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalogue_impact, "LOCK_TIMEOUT", "200ms")
    before = _state()
    with SessionLocal() as holder:
        holder.execute(text("SELECT 1 FROM catalogue_services WHERE id = :s FOR UPDATE"), {"s": PLAIN})
        resp = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
        holder.rollback()
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "CATALOGUE_BUSY")
    assert _state() == before


def test_preview_and_real_changes_in_parallel(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    """Previews and real changes on one branch at once: only domain outcomes, nothing half-applied."""

    def real(status: str) -> str:
        with SessionLocal() as db:
            admin_row = db.scalar(select(User).where(User.role == "admin"))
            version = db.scalar(select(CatalogueService.version).where(CatalogueService.id == PLAIN))
            try:
                svc.set_service_status(db, admin_row, PLAIN, status, None, version)
                return "ok"
            except Exception as exc:  # noqa: BLE001 - reported
                return getattr(exc, "code", type(exc).__name__)

    def previewed() -> str:
        with SessionLocal() as db:
            admin_row = db.scalar(select(User).where(User.role == "admin"))
            db.commit()
            change = catalogue_impact.ProposedChange("specialisation", SPEC, "status", status="planned")
            try:
                catalogue_impact.preview(db, admin_row, change)
                return "ok"
            except Exception as exc:  # noqa: BLE001 - reported
                return getattr(exc, "code", type(exc).__name__)

    jobs = [previewed, lambda: real("inactive"), previewed, lambda: real("planned"), previewed]
    barrier = threading.Barrier(len(jobs))
    results: list[str] = []

    def run(job: Any) -> None:
        barrier.wait()
        results.append(job())

    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == len(jobs) and set(results) <= {
        "ok",
        "VERSION_CONFLICT",
        "INVALID_STATUS_TRANSITION",
    }, results
    with SessionLocal() as db:
        version = db.scalar(select(CatalogueService.version).where(CatalogueService.id == PLAIN))
        changes = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == PLAIN))
    assert version == 1 + changes  # every applied change exactly once; previews left nothing


# --- performance --------------------------------------------------------------------------------------------


def _queries(client: TestClient, admin: dict[str, str]) -> int:
    statements: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert (
            _preview(
                client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"}
            ).status_code
            == 200
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(statements)


def test_fixed_number_of_queries(client: TestClient, admin: dict[str, str], world: World) -> None:
    small = _queries(client, admin)
    for _ in range(20):
        world.master(electric=None)
    with SessionLocal() as db:  # a much larger branch: every service of category 2 under SPEC, all active
        db.execute(
            update(CatalogueService)
            .where(
                CatalogueService.specialisation_id.in_(
                    select(CatalogueSpecialisation.id).where(
                        CatalogueSpecialisation.category_id == seed_id("cm-c2")
                    )
                )
            )
            .values(specialisation_id=SPEC, status="active")
        )
        db.commit()
    large = _queries(client, admin)
    assert large == small, (small, large)
    assert small <= 40, small


def test_preview_session_must_be_clean(world: World) -> None:
    """The preview refuses a session with unsaved work, so a rollback can never discard someone's change."""
    with SessionLocal() as db:
        admin_row = db.scalar(select(User).where(User.role == "admin"))
        service = db.get(CatalogueService, PLAIN)
        service.review_note = "pending"
        with pytest.raises(RuntimeError):
            catalogue_impact.preview(
                db, admin_row, catalogue_impact.ProposedChange("service", PLAIN, "status", status="inactive")
            )
