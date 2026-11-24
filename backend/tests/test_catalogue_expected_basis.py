"""Applying a previewed catalogue change with `expected_basis` (step 4.5.4.3, R-CAT-18) — PostgreSQL."""

import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from app.models import CatalogueService, CatalogueSpecialisation, User
from app.services import catalogue as svc
from app.services import catalogue_impact
from app.services.catalogue_seed import seed_id
from tests.conftest import auth, versioned
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
from tests.test_catalogue_impact_preview import (
    CASES,
    PLANNED_CATEGORY,
    _masters,
    _resolve,
    _state,
    _tree_services,
    _version,
)

URL = "/api/v1/admin/catalogue/impact"
BASE = "/api/v1/admin/catalogue"
OTHER_CATEGORY = seed_id("cm-c2")
SPEC_SERVICES = [seed_id(f"cm-s01-{n}") for n in (1, 2, 3, 4)]
FAR_SPEC = seed_id("cm-s14")  # a specialisation of category 2: a move into another category


@pytest.fixture
def world(client: TestClient) -> Iterator[World]:
    world = build_world()
    with SessionLocal() as db:
        db.execute(
            update(CatalogueService).where(CatalogueService.id == UNCONFIGURED).values(status="inactive")
        )
        db.commit()
    yield world


@pytest.fixture
def admin(world: World, admin_token: str) -> dict[str, str]:
    return auth(admin_token)


def _preview(
    client: TestClient, admin: dict[str, str], entity: str, entity_id: Any, change: dict[str, Any]
) -> Any:
    resp = client.post(URL, json={"entity": entity, "id": str(entity_id), "change": change}, headers=admin)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _apply(
    client: TestClient,
    admin: dict[str, str],
    preview: dict[str, Any],
    method: str,
    path: str,
    body: dict[str, Any],
    entity: str,
    entity_id: Any,
) -> Any:
    payload = body | {
        "expected_version": _version(preview, entity, entity_id),
        "expected_basis": preview["basis"],
    }
    return getattr(client, method)(f"{BASE}{path}", json=payload, headers=admin)


def _outdated(resp: Any) -> dict[str, list[dict[str, Any]]]:
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "IMPACT_PREVIEW_OUTDATED"
    details: dict[str, list[dict[str, Any]]] = error["details"]
    return details


def _ids(details: dict[str, list[dict[str, Any]]], key: str) -> set[tuple[str, str]]:
    return {(item["kind"], item["id"]) for item in details[key]}


def _change(client: TestClient, admin: dict[str, str], method: str, path: str, body: dict[str, Any]) -> None:
    url = f"{BASE}{path}"
    resp = getattr(client, method)(url, json=versioned(url, body), headers=admin)
    assert resp.status_code in (200, 201), resp.text


# --- success and backward compatibility ---------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_previewed_change_applies_with_its_basis(
    client: TestClient, admin: dict[str, str], world: World, name: str
) -> None:
    entity, entity_id, change, (method, path, body) = CASES[name]
    _masters(world)
    if name == "activate_hold":
        with SessionLocal() as db:
            db.execute(update(CatalogueService).where(CatalogueService.id == PLAIN).values(status="hold"))
            db.commit()
    preview = _preview(client, admin, entity, entity_id, _resolve(change, world))
    resp = _apply(client, admin, preview, method, path, _resolve(body, world), entity, entity_id)
    assert resp.status_code == 200, resp.text
    tree = _tree_services(client, admin)
    for item in preview["services"]:
        current = tree[item["service_id"]]
        assert item["after"] == {
            "orderable": current["orderable"],
            "eligible_masters": current["eligible_masters"],
            "reasons": current["orderable_reasons"],
        }


def test_without_basis_nothing_changes(client: TestClient, admin: dict[str, str], world: World) -> None:
    url = f"{BASE}/services/{PLAIN}/status"
    stale = client.post(url, json={"status": "inactive", "expected_version": 9}, headers=admin)
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert (
        client.post(url, json={"status": "inactive", "expected_version": 1}, headers=admin).status_code == 200
    )
    null_basis = client.post(
        url, json={"status": "planned", "expected_version": 2, "expected_basis": None}, headers=admin
    )
    assert null_basis.status_code == 200  # an explicit null is the same as no basis


def test_basis_is_checked_before_the_entry_version(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    preview = _preview(client, admin, "service", PLAIN, {"kind": "status", "status": "inactive"})
    _change(client, admin, "patch", f"/services/{PLAIN}", {"review_note": "x"})
    before = _state()
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "post",
            f"/services/{PLAIN}/status",
            {"status": "inactive"},
            "service",
            PLAIN,
        )
    )
    assert details["changed"] == [{"kind": "service", "id": str(PLAIN), "expected": 1, "current": 2}]
    assert _state() == before


# --- versions of every kind of row --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("category", lambda w: ("patch", f"/categories/{CATEGORY}", {"description": "x"}, CATEGORY)),
        ("specialisation", lambda w: ("patch", f"/specialisations/{SPEC}", {"description": "x"}, SPEC)),
        ("service", lambda w: ("patch", f"/services/{REGULATED}", {"review_note": "x"}, REGULATED)),
        (
            "qualification",
            lambda w: ("patch", f"/qualifications/{w.electric}", {"description": "x"}, w.electric),
        ),
    ],
)
def test_any_changed_version_makes_the_preview_outdated(
    client: TestClient, admin: dict[str, str], world: World, kind: str, change: Callable[[World], Any]
) -> None:
    preview = _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"})
    method, path, body, changed_id = change(world)
    if kind == "qualification":  # qualification types are edited without a version
        assert client.patch(f"{BASE}{path}", json=body, headers=admin).status_code == 200
    else:
        _change(client, admin, method, path, body)
    before = _state()
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "post",
            f"/categories/{CATEGORY}/status",
            {"status": "inactive"},
            "category",
            CATEGORY,
        )
    )
    assert _ids(details, "changed") == {(kind, str(changed_id))}
    assert details["added"] == [] and details["removed"] == []
    assert _state() == before  # no data, audit entry or event


# --- composition of the branch ------------------------------------------------------------------------------


def test_new_service_in_the_branch(client: TestClient, admin: dict[str, str], world: World) -> None:
    preview = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
    created = client.post(
        f"{BASE}/services", json={"specialisation_id": str(SPEC), "name": "Jauna"}, headers=admin
    )
    assert created.status_code == 201
    before = _state()
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "post",
            f"/specialisations/{SPEC}/status",
            {"status": "planned"},
            "specialisation",
            SPEC,
        )
    )
    assert _ids(details, "added") == {("service", created.json()["id"])}
    assert _state() == before


def test_service_moved_out_of_and_into_the_branch(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    out_preview = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
    _change(client, admin, "patch", f"/services/{REGULATED}", {"specialisation_id": str(OTHER_SPEC)})
    details = _outdated(
        _apply(
            client,
            admin,
            out_preview,
            "post",
            f"/specialisations/{SPEC}/status",
            {"status": "planned"},
            "specialisation",
            SPEC,
        )
    )
    assert ("service", str(REGULATED)) in _ids(details, "removed")

    in_preview = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
    moved_in = seed_id("cm-s02-2")
    _change(client, admin, "patch", f"/services/{moved_in}", {"specialisation_id": str(SPEC)})
    details = _outdated(
        _apply(
            client,
            admin,
            in_preview,
            "post",
            f"/specialisations/{SPEC}/status",
            {"status": "planned"},
            "specialisation",
            SPEC,
        )
    )
    assert ("service", str(moved_in)) in _ids(details, "added")


def test_new_or_moved_specialisation_in_the_category(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    preview = _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"})
    created = client.post(
        f"{BASE}/specialisations", json={"category_id": str(CATEGORY), "name": "Jauna"}, headers=admin
    )
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "post",
            f"/categories/{CATEGORY}/status",
            {"status": "inactive"},
            "category",
            CATEGORY,
        )
    )
    assert ("specialisation", created.json()["id"]) in _ids(details, "added")

    preview = _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"})
    _change(client, admin, "patch", f"/specialisations/{SPEC}", {"category_id": str(OTHER_CATEGORY)})
    before = _state()
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "post",
            f"/categories/{CATEGORY}/status",
            {"status": "inactive"},
            "category",
            CATEGORY,
        )
    )
    removed = _ids(details, "removed")
    assert ("specialisation", str(SPEC)) in removed and {
        ("service", str(s)) for s in SPEC_SERVICES
    } <= removed
    assert _state() == before


# --- moves: both branches -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "touched",
    [
        ("specialisation", SPEC, "patch", f"/specialisations/{SPEC}", {"description": "x"}),  # old branch
        (
            "specialisation",
            FAR_SPEC,
            "patch",
            f"/specialisations/{FAR_SPEC}",
            {"description": "x"},
        ),  # new branch
        (
            "category",
            OTHER_CATEGORY,
            "patch",
            f"/categories/{OTHER_CATEGORY}",
            {"description": "x"},
        ),  # new parent's
        ("category", CATEGORY, "patch", f"/categories/{CATEGORY}", {"description": "x"}),  # old parent's
    ],
    ids=["old_specialisation", "new_specialisation", "new_category", "old_category"],
)
def test_service_move_checks_both_branches(
    client: TestClient,
    admin: dict[str, str],
    world: World,
    touched: tuple[str, uuid.UUID, str, str, dict[str, Any]],
) -> None:
    kind, touched_id, method, path, body = touched
    preview = _preview(client, admin, "service", PLAIN, {"kind": "move", "target_id": str(FAR_SPEC)})
    _change(client, admin, method, path, body)
    before = _state()
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "patch",
            f"/services/{PLAIN}",
            {"specialisation_id": str(FAR_SPEC)},
            "service",
            PLAIN,
        )
    )
    assert _ids(details, "changed") == {(kind, str(touched_id))}
    assert _state() == before


@pytest.mark.parametrize("touched", [CATEGORY, PLANNED_CATEGORY], ids=["old_category", "new_category"])
def test_specialisation_move_checks_both_categories(
    client: TestClient, admin: dict[str, str], world: World, touched: uuid.UUID
) -> None:
    preview = _preview(
        client, admin, "specialisation", SPEC, {"kind": "move", "target_id": str(PLANNED_CATEGORY)}
    )
    _change(client, admin, "patch", f"/categories/{touched}", {"description": "x"})
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "patch",
            f"/specialisations/{SPEC}",
            {"category_id": str(PLANNED_CATEGORY)},
            "specialisation",
            SPEC,
        )
    )
    assert _ids(details, "changed") == {("category", str(touched))}


def test_a_different_change_than_previewed_is_refused(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    """A status preview's basis does not cover a move: the move's wider scope shows as added rows."""
    preview = _preview(client, admin, "service", PLAIN, {"kind": "status", "status": "inactive"})
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "patch",
            f"/services/{PLAIN}",
            {"specialisation_id": str(OTHER_SPEC)},
            "service",
            PLAIN,
        )
    )
    assert ("specialisation", str(OTHER_SPEC)) in _ids(details, "added")


# --- qualification types: old and new sets ------------------------------------------------------------------


@pytest.mark.parametrize("which", ["old", "new"])
def test_requirements_check_old_and_new_types(
    client: TestClient, admin: dict[str, str], world: World, which: str
) -> None:
    preview = _preview(
        client, admin, "service", REGULATED, {"kind": "requirements", "qualification_ids": [str(world.gas)]}
    )  # removes electric, adds gas
    touched = world.electric if which == "old" else world.gas
    assert (
        client.patch(f"{BASE}/qualifications/{touched}", json={"description": "x"}, headers=admin).status_code
        == 200
    )
    details = _outdated(
        _apply(
            client,
            admin,
            preview,
            "put",
            f"/services/{REGULATED}/qualifications",
            {"qualification_ids": [str(world.gas)]},
            "service",
            REGULATED,
        )
    )
    assert _ids(details, "changed") == {("qualification", str(touched))}


# --- input --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "basis",
    [
        [{"kind": "service", "id": str(PLAIN), "version": 1}] * 2,  # duplicate
        [{"kind": "master", "id": str(PLAIN), "version": 1}],
        [{"kind": "service", "id": str(PLAIN), "version": 0}],
        [{"kind": "service", "id": str(PLAIN)}],
        [{"kind": "service", "id": str(uuid.uuid4()), "version": 1}] * 1
        + [{"kind": "service", "id": str(uuid.uuid4()), "version": 1} for _ in range(2000)],
    ],
    ids=["duplicate", "unknown_kind", "version_zero", "no_version", "over_2000"],
)
def test_malformed_basis(client: TestClient, admin: dict[str, str], basis: list[dict[str, Any]]) -> None:
    body = {"status": "inactive", "expected_version": 1, "expected_basis": basis}
    before = _state()
    assert client.post(f"{BASE}/services/{PLAIN}/status", json=body, headers=admin).status_code == 422
    assert _state() == before


def test_basis_only_where_a_preview_exists(client: TestClient, admin: dict[str, str]) -> None:
    body = {"description": "x", "expected_version": 1, "expected_basis": []}
    assert client.patch(f"{BASE}/categories/{CATEGORY}", json=body, headers=admin).status_code == 422


def test_empty_basis_is_outdated_not_ignored(client: TestClient, admin: dict[str, str], world: World) -> None:
    resp = client.post(
        f"{BASE}/services/{PLAIN}/status",
        json={"status": "inactive", "expected_version": 1, "expected_basis": []},
        headers=admin,
    )
    assert _ids(_outdated(resp), "added") >= {("service", str(PLAIN))}


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _apply_in_thread(fx_admin: uuid.UUID, preview: dict[str, Any], outcome: list[str]) -> None:
    from app.schemas.catalogue import StatusChange

    data = StatusChange(
        status="planned",
        expected_version=_version(preview, "specialisation", SPEC),
        expected_basis=preview["basis"],
    )
    with SessionLocal() as db:
        admin = db.get(User, fx_admin)
        try:
            change = catalogue_impact.ProposedChange("specialisation", SPEC, "status", status="planned")
            expected = [
                catalogue_impact.BasisItem(b.kind, b.id, b.version) for b in data.expected_basis or []
            ]
            catalogue_impact.check_basis(db, change, expected)
            svc.set_specialisation_status(db, admin, SPEC, "planned", None, data.expected_version)
            outcome.append("ok")
        except Exception as exc:  # noqa: BLE001 - reported
            outcome.append(getattr(exc, "code", type(exc).__name__))


def _admin_id() -> uuid.UUID:
    with SessionLocal() as db:
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
    assert admin_id is not None
    return admin_id


@pytest.mark.parametrize("holder_change", ["service_changed", "service_created"])
def test_change_racing_with_the_application(
    client: TestClient, admin: dict[str, str], world: World, holder_change: str
) -> None:
    """Another transaction holds a row of the branch: the application waits, sees the change, refuses."""
    preview = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
    outcome: list[str] = []
    with SessionLocal() as holder:
        if holder_change == "service_changed":
            holder.execute(text("SELECT 1 FROM catalogue_services WHERE id = :s FOR UPDATE"), {"s": PLAIN})
            holder.execute(
                update(CatalogueService)
                .where(CatalogueService.id == PLAIN)
                .values(version=2, review_note="x")
            )
        else:
            holder.execute(
                text(
                    "INSERT INTO catalogue_services "
                    "(id, specialisation_id, name, w_id, status, source, sort_order) "
                    "VALUES (:id, :spec, 'Sacīkstes', 'W991', 'inactive', 'admin', 99)"
                ),
                {"id": uuid.uuid4(), "spec": SPEC},
            )
        thread = threading.Thread(target=_apply_in_thread, args=(_admin_id(), preview, outcome))
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the application must wait for the branch lock"
        holder.commit()
    thread.join(timeout=30)
    assert outcome == ["IMPACT_PREVIEW_OUTDATED"]
    with SessionLocal() as db:
        assert (
            db.scalar(select(CatalogueSpecialisation.status).where(CatalogueSpecialisation.id == SPEC))
            == "active"
        )


def test_busy_branch(
    client: TestClient, admin: dict[str, str], world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalogue_impact, "LOCK_TIMEOUT", "200ms")
    preview = _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"})
    before = _state()
    with SessionLocal() as holder:
        holder.execute(text("SELECT 1 FROM catalogue_services WHERE id = :s FOR UPDATE"), {"s": PLAIN})
        resp = _apply(
            client,
            admin,
            preview,
            "post",
            f"/specialisations/{SPEC}/status",
            {"status": "planned"},
            "specialisation",
            SPEC,
        )
        holder.rollback()
    assert (resp.status_code, resp.json()["error"]["code"]) == (409, "CATALOGUE_BUSY")
    assert _state() == before


def test_parallel_applications_never_deadlock(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    """Previewed changes on overlapping branches (category, specialisation, services, a move, requirements)
    applied at once, with plain changes in between: one order of locks, no deadlock, nothing half-applied."""
    admin_id = _admin_id()
    previews = {
        "category": _preview(client, admin, "category", CATEGORY, {"kind": "status", "status": "inactive"}),
        "spec": _preview(client, admin, "specialisation", SPEC, {"kind": "status", "status": "planned"}),
        "move": _preview(client, admin, "service", PLAIN, {"kind": "move", "target_id": str(OTHER_SPEC)}),
        "req": _preview(
            client,
            admin,
            "service",
            REGULATED,
            {"kind": "requirements", "qualification_ids": [str(world.gas)]},
        ),
    }

    def run(name: str) -> str:
        with SessionLocal() as db:
            actor = db.get(User, admin_id)
            try:
                if name == "category":
                    p = previews[name]
                    change = catalogue_impact.ProposedChange(
                        "category", CATEGORY, "status", status="inactive"
                    )
                    catalogue_impact.check_basis(
                        db,
                        change,
                        [
                            catalogue_impact.BasisItem(b["kind"], uuid.UUID(b["id"]), b["version"])
                            for b in p["basis"]
                        ],
                    )
                    svc.set_category_status(
                        db, actor, CATEGORY, "inactive", None, _version(p, "category", CATEGORY)
                    )
                elif name == "spec":
                    p = previews[name]
                    change = catalogue_impact.ProposedChange(
                        "specialisation", SPEC, "status", status="planned"
                    )
                    catalogue_impact.check_basis(
                        db,
                        change,
                        [
                            catalogue_impact.BasisItem(b["kind"], uuid.UUID(b["id"]), b["version"])
                            for b in p["basis"]
                        ],
                    )
                    svc.set_specialisation_status(
                        db, actor, SPEC, "planned", None, _version(p, "specialisation", SPEC)
                    )
                elif name == "move":
                    from app.schemas.catalogue import ServiceUpdate

                    p = previews[name]
                    change = catalogue_impact.ProposedChange("service", PLAIN, "move", target_id=OTHER_SPEC)
                    catalogue_impact.check_basis(
                        db,
                        change,
                        [
                            catalogue_impact.BasisItem(b["kind"], uuid.UUID(b["id"]), b["version"])
                            for b in p["basis"]
                        ],
                    )
                    svc.update_service(
                        db,
                        actor,
                        PLAIN,
                        ServiceUpdate(
                            expected_version=_version(p, "service", PLAIN), specialisation_id=OTHER_SPEC
                        ),
                    )
                elif name == "req":
                    p = previews[name]
                    change = catalogue_impact.ProposedChange(
                        "service", REGULATED, "requirements", qualification_ids=(world.gas,)
                    )
                    catalogue_impact.check_basis(
                        db,
                        change,
                        [
                            catalogue_impact.BasisItem(b["kind"], uuid.UUID(b["id"]), b["version"])
                            for b in p["basis"]
                        ],
                    )
                    svc.set_service_requirements(
                        db, actor, REGULATED, [world.gas], _version(p, "service", REGULATED)
                    )
                else:
                    svc.set_qualification_status(db, actor, world.electric, "archived", "Vecs", 1)
                return "ok"
            except DBAPIError as exc:
                return f"db:{type(exc.orig).__name__}"
            except Exception as exc:  # noqa: BLE001 - reported
                return getattr(exc, "code", type(exc).__name__)

    names = ["category", "spec", "move", "req", "archive"]
    barrier = threading.Barrier(len(names))
    results: dict[str, str] = {}

    def job(name: str) -> None:
        barrier.wait()
        results[name] = run(name)

    threads = [threading.Thread(target=job, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == len(names)
    assert not [r for r in results.values() if r.startswith("db:")], results
    allowed = {
        "ok",
        "IMPACT_PREVIEW_OUTDATED",
        "VERSION_CONFLICT",
        "QUALIFICATION_IN_USE",
        "QUALIFICATION_ARCHIVED",
    }
    assert set(results.values()) <= allowed, results
    # Every overlapping previewed change but the first to commit saw a changed basis.
    assert list(results.values()).count("ok") >= 1
