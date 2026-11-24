from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuditLog
from tests.conftest import auth, register, versioned

BASE = "/api/v1/admin/catalogue"


@pytest.fixture
def admin(client: TestClient, admin_token: str) -> dict[str, str]:
    return auth(admin_token)


def _post(
    client: TestClient, headers: dict[str, str], path: str, body: dict[str, Any], code: int = 201
) -> Any:
    resp = client.post(f"{BASE}{path}", json=body, headers=headers)
    assert resp.status_code == code, resp.text
    return resp.json()


def _chain(client: TestClient, headers: dict[str, str], **service: Any) -> tuple[str, str, dict[str, Any]]:
    category = _post(client, headers, "/categories", {"name": "Santehnika"})
    spec = _post(
        client, headers, "/specialisations", {"category_id": category["id"], "name": "Poda meistars"}
    )
    svc = _post(
        client, headers, "/services", {"specialisation_id": spec["id"], "name": "Poda nomaiņa"} | service
    )
    return category["id"], spec["id"], svc


def _status(
    client: TestClient,
    headers: dict[str, str],
    kind: str,
    entity_id: str,
    status: str,
    reason: str | None = None,
) -> Any:
    url = f"{BASE}/{kind}/{entity_id}/status"
    return client.post(url, json=versioned(url, {"status": status, "reason": reason}), headers=headers)


def test_catalogue_endpoints_require_admin(client: TestClient) -> None:
    assert client.get(f"{BASE}/tree").status_code == 401
    for role in ("client", "master"):
        headers = auth(register(client, role)["access_token"])
        assert client.get(f"{BASE}/tree", headers=headers).status_code == 403
        assert (
            client.post(f"{BASE}/categories", json={"name": "X kategorija"}, headers=headers).status_code
            == 403
        )
        assert client.get(f"{BASE}/export", headers=headers).status_code == 403


def test_create_hierarchy_assigns_w_id_and_audits(client: TestClient, admin: dict[str, str]) -> None:
    _, spec_id, svc = _chain(client, admin)
    assert svc["w_id"] == "W071" and svc["status"] == "inactive" and svc["source"] == "admin"
    second = _post(client, admin, "/services", {"specialisation_id": spec_id, "name": "Poda uzstādīšana"})
    assert second["w_id"] == "W072" and second["sort_order"] == 1
    tree = client.get(f"{BASE}/tree", headers=admin).json()
    assert tree["can_create"] is True
    assert [s["w_id"] for s in tree["categories"][0]["specialisations"][0]["services"]] == ["W071", "W072"]
    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action)))
    assert {
        "catalogue.category.created",
        "catalogue.specialisation.created",
        "catalogue.service.created",
    } <= actions


def test_new_entries_cannot_start_active(client: TestClient, admin: dict[str, str]) -> None:
    resp = client.post(f"{BASE}/categories", json={"name": "Aktīva", "status": "active"}, headers=admin)
    assert resp.status_code == 422


def test_ids_cannot_be_changed_through_api_or_db(client: TestClient, admin: dict[str, str]) -> None:
    _, _, svc = _chain(client, admin)
    for body in ({"w_id": "W999"}, {"id": "00000000-0000-0000-0000-000000000001"}):
        url = f"{BASE}/services/{svc['id']}"
        resp = client.patch(url, json=versioned(url, body), headers=admin)
        assert resp.status_code == 422 and body.popitem()[0] in resp.text  # refused for the identifier itself
    url = f"{BASE}/services/{svc['id']}"
    renamed = client.patch(url, json=versioned(url, {"name": "Jauns nosaukums"}), headers=admin).json()
    assert (renamed["id"], renamed["w_id"], renamed["version"]) == (svc["id"], svc["w_id"], 2)
    for sql in (
        "UPDATE catalogue_services SET w_id = 'W500'",
        "UPDATE catalogue_services SET id = gen_random_uuid()",
        "DELETE FROM catalogue_services",
        "DELETE FROM catalogue_categories",
    ):
        with SessionLocal() as db, pytest.raises(DBAPIError):
            db.execute(text(sql))


@pytest.mark.parametrize(("source", "w_id"), [("admin", "W005"), ("kvc_v1", "W071"), ("admin", "X071")])
def test_db_enforces_w_id_ranges(client: TestClient, admin: dict[str, str], source: str, w_id: str) -> None:
    _, spec_id, _ = _chain(client, admin)
    with SessionLocal() as db, pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO catalogue_services (id, specialisation_id, w_id, name, status, source) "
                "VALUES (gen_random_uuid(), :spec, :w, 'KVC test', 'inactive', :src)"
            ),
            {"spec": spec_id, "w": w_id, "src": source},
        )


def test_rejected_w_ids_are_never_reused(client: TestClient, admin: dict[str, str]) -> None:
    _, spec_id, svc = _chain(client, admin, status="draft")
    assert _status(client, admin, "services", svc["id"], "rejected", "Dublikāts").status_code == 200
    again = _post(client, admin, "/services", {"specialisation_id": spec_id, "name": "Poda nomaiņa"})
    assert again["w_id"] == "W072"


def test_sibling_names_are_unique_until_archived(client: TestClient, admin: dict[str, str]) -> None:
    category = _post(client, admin, "/categories", {"name": "Apkure"})
    resp = client.post(f"{BASE}/categories", json={"name": "apkure"}, headers=admin)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "NAME_TAKEN"
    assert (
        _status(client, admin, "categories", category["id"], "archived", "Vairs neizmanto").status_code == 200
    )
    _post(client, admin, "/categories", {"name": "Apkure"})


def test_service_status_rules(client: TestClient, admin: dict[str, str]) -> None:
    _, _, svc = _chain(client, admin, status="draft")
    resp = _status(client, admin, "services", svc["id"], "rejected")
    assert resp.json()["error"]["code"] == "REASON_REQUIRED"
    assert (
        _status(client, admin, "services", svc["id"], "hold").json()["error"]["code"]
        == "INVALID_STATUS_TRANSITION"
    )
    assert _status(client, admin, "services", svc["id"], "active").json()["status"] == "active"
    assert _status(client, admin, "services", svc["id"], "hold", "Augsts risks").json()["status"] == "hold"

    resp = _status(client, admin, "services", svc["id"], "active")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "HOLD_ACTIVATION_REQUIRED"
    hold_url = f"{BASE}/services/{svc['id']}/activate-hold"
    no_confirm = client.post(hold_url, json=versioned(hold_url, {"reason": "Pārbaudīts"}), headers=admin)
    assert no_confirm.status_code == 422
    resp = client.post(
        hold_url, json=versioned(hold_url, {"confirm": True, "reason": "Pārbaudīts"}), headers=admin
    )
    assert resp.status_code == 200 and resp.json()["status"] == "active"


def test_regulated_service_needs_configured_qualification(client: TestClient, admin: dict[str, str]) -> None:
    _, _, svc = _chain(client, admin, qualification_required=True)
    assert svc["qualifications_ready"] is False
    resp = _status(client, admin, "services", svc["id"], "active")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "QUALIFICATION_NOT_CONFIGURED"

    qualification = _post(
        client, admin, "/qualifications", {"name": "Sertifikāts A", "requires_expiry_date": True}
    )
    assert qualification["status"] == "draft"
    req_url = f"{BASE}/services/{svc['id']}/qualifications"
    put = client.put(
        req_url, json=versioned(req_url, {"qualification_ids": [qualification["id"]]}), headers=admin
    )
    assert put.json()["qualifications_ready"] is False  # draft qualification is not configured yet
    assert _status(client, admin, "services", svc["id"], "active").status_code == 409

    assert _status(client, admin, "qualifications", qualification["id"], "active").status_code == 200
    assert _status(client, admin, "services", svc["id"], "active").json()["status"] == "active"

    remove = client.put(req_url, json=versioned(req_url, {"qualification_ids": []}), headers=admin)
    assert remove.status_code == 409
    archive = _status(client, admin, "qualifications", qualification["id"], "archived", "Novecojis")
    assert archive.status_code == 409 and archive.json()["error"]["code"] == "QUALIFICATION_IN_USE"


def test_whole_specialisation_requirement_applies_to_its_services(
    client: TestClient, admin: dict[str, str]
) -> None:
    _, spec_id, svc = _chain(client, admin)
    assert _status(client, admin, "services", svc["id"], "active").status_code == 200
    # Marking the whole specialisation regulated would leave an active service without a qualification.
    url = f"{BASE}/specialisations/{spec_id}"
    resp = client.patch(url, json=versioned(url, {"qualification_required": True}), headers=admin)
    assert resp.status_code == 409


def test_cannot_move_under_archived_parent(client: TestClient, admin: dict[str, str]) -> None:
    category_id, _, svc = _chain(client, admin)
    other = _post(client, admin, "/specialisations", {"category_id": category_id, "name": "Krānu meistars"})
    assert _status(client, admin, "specialisations", other["id"], "archived", "Slēgts").status_code == 200
    url = f"{BASE}/services/{svc['id']}"
    resp = client.patch(url, json=versioned(url, {"specialisation_id": other["id"]}), headers=admin)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "PARENT_ARCHIVED"


def test_reorder_requires_all_visible_siblings(client: TestClient, admin: dict[str, str]) -> None:
    _, spec_id, first = _chain(client, admin)
    second = _post(
        client, admin, "/services", {"specialisation_id": spec_id, "name": "Skalošanas kastes remonts"}
    )
    path = f"{BASE}/specialisations/{spec_id}/services/order"
    assert client.put(path, json={"ids": [second["id"]]}, headers=admin).status_code == 422
    assert client.put(path, json={"ids": [second["id"], first["id"]]}, headers=admin).status_code == 204
    services = client.get(f"{BASE}/tree", headers=admin).json()["categories"][0]["specialisations"][0][
        "services"
    ]
    assert [s["w_id"] for s in services] == ["W072", "W071"]


def test_staging_cannot_create_entries_but_can_edit(
    client: TestClient, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    category_id, _, _ = _chain(client, admin)
    monkeypatch.setattr(get_settings(), "catalogue_role", "receiver")
    for path, body in (("/categories", {"name": "Jauna"}), ("/qualifications", {"name": "Q kvalifikācija"})):
        resp = client.post(f"{BASE}{path}", json=body, headers=admin)
        assert resp.status_code == 409 and resp.json()["error"]["code"] == "W_ID_AUTHORITY_REQUIRED"
    assert client.get(f"{BASE}/tree", headers=admin).json()["can_create"] is False
    url = f"{BASE}/categories/{category_id}"
    assert client.patch(url, json=versioned(url, {"description": "x"}), headers=admin).status_code == 200


def test_every_change_is_audited(client: TestClient, admin: dict[str, str]) -> None:
    category_id, _, svc = _chain(client, admin)
    url = f"{BASE}/categories/{category_id}"
    client.patch(url, json=versioned(url, {"description": "Apraksts"}), headers=admin)
    _status(client, admin, "services", svc["id"], "planned")
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditLog).where(AuditLog.entity_id == svc["id"]).order_by(AuditLog.created_at)
        ).all()
        assert [r.action for r in rows] == ["catalogue.service.created", "catalogue.service.status_changed"]
        assert rows[-1].before["status"] == "inactive" and rows[-1].after["status"] == "planned"  # type: ignore[index]
        assert (
            db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_id == category_id))
            == 2
        )
