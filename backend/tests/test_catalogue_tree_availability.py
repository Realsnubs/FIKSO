"""Availability in the admin catalogue tree (step 4.5.2, R-CAT-03): every service carries `eligible_masters`,
`orderable` and `orderable_reasons` from `catalogue.availability`, with the tree otherwise unchanged."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update

from app.core.db import SessionLocal, engine
from app.models import (
    AuditLog,
    CatalogueCategory,
    CatalogueService,
    CatalogueSpecialisation,
    DomainEvent,
    MasterProfile,
)
from app.schemas.catalogue import CategoryOut, ServiceOut, SpecialisationOut
from app.services import catalogue
from app.services.catalogue_seed import seed_id
from tests.conftest import auth, register, versioned
from tests.test_catalogue_availability import (
    CATEGORY,
    PLAIN,
    REGULATED,
    SPEC,
    SPEC_REQUIRED,
    UNCONFIGURED,
    World,
    build_world,
)

OTHER_SPEC = seed_id("cm-s02")

TREE = "/api/v1/admin/catalogue/tree"
NEW_FIELDS = {"eligible_masters", "orderable", "orderable_reasons"}


@pytest.fixture
def world(client: TestClient) -> World:
    return build_world()


@pytest.fixture
def admin(world: World, admin_token: str) -> Iterator[dict[str, str]]:
    yield auth(admin_token)


def _tree(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(TREE, headers=headers)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _services(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        service["id"]: service
        for category in body["categories"]
        for spec in category["specialisations"]
        for service in spec["services"]
    }


def _set(model: Any, entity_id: Any, **values: Any) -> None:
    with SessionLocal() as db:
        db.execute(update(model).where(model.id == entity_id).values(**values))
        db.commit()


def _reasons(service: dict[str, Any]) -> list[str]:
    return [r["code"] for r in service["orderable_reasons"]]


# --- structure ----------------------------------------------------------------------------------------------


def test_tree_keeps_its_structure_and_adds_three_fields(client: TestClient, admin: dict[str, str]) -> None:
    body = _tree(client, admin)
    assert set(body) == {"catalogue_role", "can_create", "categories", "qualifications"}
    category = body["categories"][0]
    spec = category["specialisations"][0]
    assert set(category) == set(CategoryOut.model_fields)
    assert set(spec) == set(SpecialisationOut.model_fields)
    for service in _services(body).values():
        assert set(service) == set(ServiceOut.model_fields) | NEW_FIELDS


def test_every_service_is_listed_whatever_its_chain(client: TestClient, admin: dict[str, str]) -> None:
    """Services under planned categories or in draft are listed with their reasons, never dropped."""
    services = _services(_tree(client, admin))
    with SessionLocal() as db:
        assert len(services) == db.scalar(select(func.count()).select_from(CatalogueService))
        planned = db.scalars(
            select(CatalogueService.id)
            .join(CatalogueSpecialisation)
            .join(CatalogueCategory)
            .where(CatalogueCategory.status == "planned")
        ).all()
    assert planned  # categories 2–3 of the seed are planned (one was activated by the fixture)
    for service_id in planned:
        service = services[str(service_id)]
        assert service["orderable"] is False and "CATEGORY_NOT_ACTIVE" in _reasons(service)


def test_other_responses_are_unchanged(client: TestClient, admin: dict[str, str]) -> None:
    """Only the tree carries availability; create/update responses keep their exact shape."""
    url = f"/api/v1/admin/catalogue/services/{PLAIN}"
    resp = client.patch(url, json=versioned(url, {"review_note": "x"}), headers=admin)
    assert resp.status_code == 200 and set(resp.json()) == set(ServiceOut.model_fields)
    url = f"/api/v1/admin/catalogue/specialisations/{OTHER_SPEC}"
    resp = client.patch(url, json=versioned(url, {"description": "x"}), headers=admin)
    assert resp.status_code == 200
    assert all(set(s) == set(ServiceOut.model_fields) for s in resp.json()["services"])


def test_only_admins_read_the_tree(client: TestClient, world: World) -> None:
    assert client.get(TREE).status_code == 401
    for role in ("master", "client"):
        assert client.get(TREE, headers=auth(register(client, role)["access_token"])).status_code == 403


# --- values -------------------------------------------------------------------------------------------------


def test_orderable_service(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master()
    world.master()
    services = _tree(client, admin)
    for service_id in (PLAIN, REGULATED, SPEC_REQUIRED):
        service = _services(services)[str(service_id)]
        assert (service["eligible_masters"], service["orderable"], service["orderable_reasons"]) == (
            2,
            True,
            [],
        )


def test_no_eligible_masters(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master(electric=None)  # eligible for PLAIN, not for REGULATED
    services = _services(_tree(client, admin))
    assert services[str(PLAIN)]["orderable"] is True
    regulated = services[str(REGULATED)]
    assert (regulated["eligible_masters"], regulated["orderable"]) == (0, False)
    assert regulated["orderable_reasons"] == [{"code": "NO_ELIGIBLE_MASTERS", "details": {}}]


def test_inactive_service(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master()
    _set(CatalogueService, PLAIN, status="hold")
    service = _services(_tree(client, admin))[str(PLAIN)]
    assert (service["status"], service["eligible_masters"], service["orderable"]) == ("hold", 1, False)
    assert service["orderable_reasons"] == [
        {"code": "SERVICE_NOT_ACTIVE", "details": {"id": str(PLAIN), "status": "hold"}}
    ]
    with SessionLocal() as db:  # reading never activates HOLD
        assert db.scalar(select(CatalogueService.status).where(CatalogueService.id == PLAIN)) == "hold"


def test_inactive_specialisation(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master()
    _set(CatalogueSpecialisation, SPEC, status="inactive")
    services = _services(_tree(client, admin))
    for service_id in (PLAIN, REGULATED):
        service = services[str(service_id)]
        assert service["status"] == "active" and service["eligible_masters"] == 1  # child rows untouched
        assert service["orderable_reasons"] == [
            {"code": "SPECIALISATION_NOT_ACTIVE", "details": {"id": str(SPEC), "status": "inactive"}}
        ]
    assert services[str(SPEC_REQUIRED)]["orderable"] is True  # another specialisation


def test_inactive_category(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master()
    _set(CatalogueCategory, CATEGORY, status="inactive")
    services = _services(_tree(client, admin))
    for service_id in (PLAIN, REGULATED):
        assert services[str(service_id)]["orderable_reasons"] == [
            {"code": "CATEGORY_NOT_ACTIVE", "details": {"id": str(CATEGORY), "status": "inactive"}}
        ]


def test_several_reasons(client: TestClient, admin: dict[str, str], world: World) -> None:
    _set(CatalogueService, UNCONFIGURED, status="planned")
    _set(CatalogueSpecialisation, SPEC, status="planned")
    service = _services(_tree(client, admin))[str(UNCONFIGURED)]
    assert _reasons(service) == [
        "SERVICE_NOT_ACTIVE",
        "SPECIALISATION_NOT_ACTIVE",
        "QUALIFICATION_NOT_CONFIGURED",
        "NO_ELIGIBLE_MASTERS",
    ]
    assert service["qualifications_ready"] is False  # the existing field agrees with the gate reason


def test_tree_values_are_exactly_the_availability_model(
    client: TestClient, admin: dict[str, str], world: World
) -> None:
    world.master()
    world.master(gas=None)
    world.master(profile="pending_approval")
    services = _services(_tree(client, admin))
    with SessionLocal() as db:
        model = catalogue.availability(db)
    assert set(services) == {str(service_id) for service_id in model}
    for service_id, item in model.items():
        service = services[str(service_id)]
        assert service["eligible_masters"] == item.eligible_masters
        assert service["orderable"] is item.orderable
        assert service["orderable_reasons"] == [{"code": r.code, "details": r.details} for r in item.reasons]


def test_values_follow_changes_at_once(client: TestClient, admin: dict[str, str], world: World) -> None:
    master = world.master()
    assert _services(_tree(client, admin))[str(PLAIN)]["eligible_masters"] == 1
    _set(MasterProfile, master, approval_status="rejected")
    service = _services(_tree(client, admin))[str(PLAIN)]
    assert (service["eligible_masters"], _reasons(service)) == (0, ["NO_ELIGIBLE_MASTERS"])


def test_reading_writes_nothing(client: TestClient, admin: dict[str, str], world: World) -> None:
    world.master()

    def snapshot() -> tuple[Any, ...]:
        with SessionLocal() as db:
            return (
                db.scalar(select(func.count()).select_from(AuditLog)),
                db.scalar(select(func.count()).select_from(DomainEvent)),
                db.scalar(select(func.max(CatalogueService.updated_at))),
                db.scalar(select(func.max(MasterProfile.updated_at))),
            )

    before = snapshot()
    _tree(client, admin)
    _tree(client, admin)
    assert snapshot() == before


# --- performance --------------------------------------------------------------------------------------------


def _query_count(client: TestClient, headers: dict[str, str]) -> int:
    statements: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        _tree(client, headers)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(statements)


def test_no_query_per_service_or_master(client: TestClient, admin: dict[str, str], world: World) -> None:
    """The query count does not grow with the catalogue or the number of masters (no N+1)."""
    small = _query_count(client, admin)
    for _ in range(15):
        world.master()
    with SessionLocal() as db:  # make every seeded service visible as active with its parents
        db.execute(update(CatalogueCategory).values(status="active"))
        db.execute(update(CatalogueSpecialisation).values(status="active"))
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.qualification_required.is_(False))
            .values(status="active")
        )
        db.commit()
    large = _query_count(client, admin)
    assert large == small
    assert small <= 16, small
