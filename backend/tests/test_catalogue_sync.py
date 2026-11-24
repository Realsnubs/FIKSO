"""Production → staging transfer (R-CAT-15/16).

One test DB plays both sides: export, wipe the catalogue, import.
"""

import copy
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, engine
from app.core.errors import AppError
from app.core.signing import generate_keypair, sign
from app.models import AuditLog, CatalogueService, DomainEvent
from app.services.catalogue import canonical_json
from app.services.catalogue_seed import seed_catalogue
from app.services.catalogue_sync import sign_package
from tests.conftest import auth, versioned

BASE = "/api/v1/admin/catalogue"
PROD_KEY_ID = "prod-test-1"
PROD_PRIVATE, PROD_PUBLIC = generate_keypair()
ENVIRONMENTS = {"issuer": "production", "receiver": "staging", "isolated": "test"}


@pytest.fixture
def admin(client: TestClient, admin_token: str) -> dict[str, str]:
    return auth(admin_token)


@pytest.fixture
def role(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Switch the single test app between production (private key) and staging (public keys only)."""
    settings = get_settings()

    def set_role(value: str, trusted: dict[str, str] | None = None, revoked: list[str] | None = None) -> None:
        monkeypatch.setattr(settings, "catalogue_role", value)
        monkeypatch.setattr(settings, "environment", ENVIRONMENTS[value])
        receiver = value == "receiver"
        monkeypatch.setattr(
            settings, "catalogue_signing_private_key", None if receiver else SecretStr(PROD_PRIVATE)
        )
        monkeypatch.setattr(settings, "catalogue_signing_key_id", None if receiver else PROD_KEY_ID)
        monkeypatch.setattr(
            settings,
            "catalogue_trusted_public_keys",
            (trusted or {PROD_KEY_ID: PROD_PUBLIC}) if receiver else {},
        )
        monkeypatch.setattr(settings, "catalogue_revoked_key_ids", revoked or [])

    return set_role


def _resign(package: dict[str, Any], role: Any, minutes: int = 1, **changes: Any) -> dict[str, Any]:
    """A newer production export of (changed) content: new package ID, later timestamp, prod signature."""
    role("issuer")
    body = copy.deepcopy(package) | changes
    exported = datetime.fromisoformat(package["exported_at"]) + timedelta(minutes=minutes)
    body |= {"package_id": str(uuid.uuid4()), "exported_at": exported.isoformat()}
    signed = sign_package(body)
    role("receiver")
    return signed


def _forge(package: dict[str, Any], private_key: str, key_id: str) -> dict[str, Any]:
    """What an attacker on staging could build: a 'production' package signed with a key they hold."""
    body = {k: v for k, v in package.items() if k != "signature"} | {"key_id": key_id}
    return body | {"signature": sign(private_key, canonical_json(body).encode())}


def _wipe_catalogue() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE catalogue_categories, catalogue_specialisations, catalogue_services, "
                "qualifications, service_qualifications, specialisation_qualifications "
                "RESTART IDENTITY CASCADE"
            )
        )


def _production_catalogue(client: TestClient, admin: dict[str, str]) -> dict[str, Any]:
    """Seed + one admin service (W143) + an active qualification required by a regulated seed service."""
    with SessionLocal() as db:
        seed_catalogue(db)
    tree = client.get(f"{BASE}/tree", headers=admin).json()
    spec = tree["categories"][0]["specialisations"][0]
    new = client.post(
        f"{BASE}/services", json={"specialisation_id": spec["id"], "name": "Jauns"}, headers=admin
    )
    assert new.json()["w_id"] == "W143"
    url = f"{BASE}/services/{new.json()['id']}/status"
    client.post(url, json=versioned(url, {"status": "active"}), headers=admin)
    q = client.post(f"{BASE}/qualifications", json={"name": "Gāzes sertifikāts"}, headers=admin).json()
    url = f"{BASE}/qualifications/{q['id']}/status"
    client.post(url, json=versioned(url, {"status": "active"}), headers=admin)
    gas = next(
        s
        for c in tree["categories"]
        for sp in c["specialisations"]
        for s in sp["services"]
        if s["w_id"] == "W129"
    )
    url = f"{BASE}/services/{gas['id']}/qualifications"
    client.put(url, json=versioned(url, {"qualification_ids": [q["id"]]}), headers=admin)
    return {"active_service_id": new.json()["id"], "gas_id": gas["id"]}


def _export(client: TestClient, admin: dict[str, str], role: Any) -> dict[str, Any]:
    role("issuer")
    resp = client.get(f"{BASE}/export", headers=admin)
    assert resp.status_code == 200, resp.text
    package: dict[str, Any] = resp.json()
    return package


def _preview(client: TestClient, admin: dict[str, str], package: dict[str, Any], code: int = 201) -> Any:
    resp = client.post(f"{BASE}/sync-imports", json=package, headers=admin)
    assert resp.status_code == code, resp.text
    return resp.json()


def _apply(client: TestClient, admin: dict[str, str], import_id: str, code: int = 200, **body: Any) -> Any:
    resp = client.post(f"{BASE}/sync-imports/{import_id}/apply", json={"confirm": True} | body, headers=admin)
    assert resp.status_code == code, resp.text
    return resp.json()


def _ids() -> dict[str, str]:
    with SessionLocal() as db:
        return {str(s.id): s.w_id for s in db.scalars(select(CatalogueService))}


def test_startup_check_enforces_key_custody() -> None:
    # The production-only requirements (S3, shared rate limits, secure cookies, origin) are satisfied here so
    # that only key custody decides; they are tested in test_production.py.
    jwt: dict[str, Any] = {
        "jwt_secret": "x" * 40,
        "storage_backend": "s3",
        "s3_private_bucket": "p",
        "s3_public_bucket": "q",
        "rate_limit_backend": "postgres",
        "cookie_secure": True,
        "app_origin": "https://app.example",
    }
    issuer = jwt | {"catalogue_signing_private_key": PROD_PRIVATE, "catalogue_signing_key_id": PROD_KEY_ID}
    receiver = jwt | {"catalogue_trusted_public_keys": {PROD_KEY_ID: PROD_PUBLIC}}
    invalid = [
        issuer | {"environment": "production", "catalogue_role": "isolated"},
        issuer | {"environment": "staging", "catalogue_role": "issuer"},
        issuer | {"environment": "local", "catalogue_role": "issuer"},
        jwt | {"environment": "production", "catalogue_role": "issuer"},  # issuer without a private key
        receiver
        | issuer
        | {"environment": "staging", "catalogue_role": "receiver"},  # receiver holding the key
        jwt | {"environment": "staging", "catalogue_role": "receiver"},  # receiver without trusted keys
        jwt
        | {
            "environment": "staging",
            "catalogue_role": "receiver",
            "catalogue_trusted_public_keys": {"k": "x"},
        },
    ]
    for values in invalid:
        with pytest.raises(ValidationError):
            Settings(**values)
    assert Settings(**issuer, environment="production", catalogue_role="issuer").catalogue_role == "issuer"
    assert Settings(**receiver, environment="staging", catalogue_role="receiver").catalogue_role == "receiver"


def test_invalid_key_errors_do_not_echo_key_material() -> None:
    broken = PROD_PRIVATE[:-4] + "!!!!"
    with pytest.raises(ValidationError) as exc:
        Settings(
            jwt_secret="x" * 40,
            environment="production",
            catalogue_role="issuer",
            catalogue_signing_private_key=broken,
            catalogue_signing_key_id=PROD_KEY_ID,
        )
    assert broken not in str(exc.value) and PROD_PRIVATE[:20] not in str(exc.value)


def test_round_trip_preserves_uuids_and_w_ids(client: TestClient, admin: dict[str, str], role: Any) -> None:
    prod = _production_catalogue(client, admin)
    production_ids = _ids()
    package = _export(client, admin, role)
    _wipe_catalogue()

    role("receiver")
    preview = _preview(client, admin, package)
    assert preview["status"] == "previewed" and not preview["preview"]["conflicts"]
    assert len(preview["preview"]["create"]) == 3 + 24 + 1 + 73
    assert _ids() == {}  # preview writes nothing to the catalogue

    applied = _apply(client, admin, preview["id"])
    assert applied["status"] == "applied"
    assert _ids() == production_ids
    tree = client.get(f"{BASE}/tree", headers=admin).json()
    services = {s["id"]: s for c in tree["categories"] for sp in c["specialisations"] for s in sp["services"]}
    assert services[prod["active_service_id"]]["status"] == "inactive"  # active arrives inactive by default
    assert services[prod["gas_id"]]["qualification_ids"] == [tree["qualifications"][0]["id"]]
    with SessionLocal() as db:  # staging never issues W-IDs, but its sequence still moved past W143
        assert db.scalar(text("SELECT last_value FROM catalogue_w_id_seq")) == 143


def test_same_package_cannot_be_applied_twice(client: TestClient, admin: dict[str, str], role: Any) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    _wipe_catalogue()
    role("receiver")
    first = _preview(client, admin, package)
    second = _preview(client, admin, package)
    _apply(client, admin, first["id"])
    err = _apply(client, admin, second["id"], code=409)
    assert err["error"]["code"] in {"PACKAGE_ALREADY_APPLIED", "IMPORT_NOT_PENDING"}
    assert _preview(client, admin, package, code=409)["error"]["code"] == "PACKAGE_ALREADY_APPLIED"


def test_identity_conflict_rejects_whole_package(
    client: TestClient, admin: dict[str, str], role: Any
) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    _wipe_catalogue()
    role("isolated")  # a separate environment that (wrongly) issued W143 for a different service
    category = client.post(f"{BASE}/categories", json={"name": "Cits"}, headers=admin).json()
    spec = client.post(
        f"{BASE}/specialisations", json={"category_id": category["id"], "name": "Cits"}, headers=admin
    )
    with SessionLocal() as db:
        db.execute(text("SELECT setval('catalogue_w_id_seq', 142, true)"))
        db.commit()
    other = client.post(
        f"{BASE}/services", json={"specialisation_id": spec.json()["id"], "name": "Cits"}, headers=admin
    )
    assert other.json()["w_id"] == "W143"

    role("receiver")
    preview = _preview(client, admin, package)
    reasons = {c["reason"] for c in preview["preview"]["conflicts"]}
    assert reasons == {"w_id_used_by_other_uuid"}
    err = _apply(client, admin, preview["id"], code=409)
    assert err["error"]["code"] == "IMPORT_CONFLICT"
    assert _ids() == {other.json()["id"]: "W143"}  # nothing written, nothing renumbered or merged


def test_updates_are_opt_in_and_never_overwrite_local_edits(
    client: TestClient, admin: dict[str, str], role: Any
) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    _wipe_catalogue()
    role("receiver")
    _apply(client, admin, _preview(client, admin, package)["id"])

    services = copy.deepcopy(package["services"])
    first, second = services[0], services[1]
    first["name"], second["name"] = "Prod rename 1", "Prod rename 2"
    renamed = _resign(package, role, services=services)
    # Staging edits the second entry locally.
    url = f"{BASE}/services/{second['id']}"
    client.patch(url, json=versioned(url, {"name": "Staging edit"}), headers=admin)

    preview = _preview(client, admin, renamed)
    updates = {u["id"]: u for u in preview["preview"]["update"]}
    assert updates[first["id"]]["locally_edited"] is False and updates[second["id"]]["changes"] == ["name"]
    assert updates[second["id"]]["locally_edited"] is True

    err = _apply(client, admin, preview["id"], code=409, apply_updates=[second["id"]])
    assert err["error"]["code"] == "LOCALLY_EDITED"
    _apply(client, admin, preview["id"], apply_updates=[first["id"]])
    with SessionLocal() as db:
        names = {str(s.id): s.name for s in db.scalars(select(CatalogueService))}
    assert names[first["id"]] == "Prod rename 1" and names[second["id"]] == "Staging edit"


def test_keep_active_is_explicit(client: TestClient, admin: dict[str, str], role: Any) -> None:
    prod = _production_catalogue(client, admin)
    package = _export(client, admin, role)
    _wipe_catalogue()
    role("receiver")
    preview = _preview(client, admin, package)
    draft_id = next(s["id"] for s in package["services"] if s["status"] == "draft")
    bad = _apply(client, admin, preview["id"], code=422, keep_active=[draft_id])
    assert bad["error"]["code"] == "INVALID_KEEP_ACTIVE"
    _apply(client, admin, preview["id"], keep_active=[prod["active_service_id"]])
    with SessionLocal() as db:
        service = db.get(CatalogueService, prod["active_service_id"])
        assert service is not None and service.status == "active"


def test_packages_are_verified(client: TestClient, admin: dict[str, str], role: Any) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    role("receiver")
    tampered = copy.deepcopy(package)
    tampered["services"][0]["name"] = "Tampered"
    assert _preview(client, admin, tampered, code=422)["error"]["code"] == "PACKAGE_SIGNATURE_INVALID"
    assert _preview(client, admin, {"format": "x"}, code=422)["error"]["code"] == "PACKAGE_INVALID"

    role("isolated")  # an isolated (local/test) export is refused even when signed with a trusted key
    isolated_package = client.get(f"{BASE}/export", headers=admin).json()
    role("receiver")
    assert (
        _preview(client, admin, isolated_package, code=422)["error"]["code"] == "PACKAGE_NOT_FROM_PRODUCTION"
    )


def test_only_staging_accepts_packages(client: TestClient, admin: dict[str, str], role: Any) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    for value in ("issuer", "isolated"):
        role(value)
        assert _preview(client, admin, package, code=409)["error"]["code"] == "IMPORT_NOT_ALLOWED"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CatalogueService)) == 73


def test_staging_cannot_sign_packages_accepted_as_production(
    client: TestClient, admin: dict[str, str], role: Any
) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    _wipe_catalogue()
    role("receiver")
    resp = client.get(f"{BASE}/export", headers=admin)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "EXPORT_NOT_ALLOWED"
    with pytest.raises(AppError) as exc:
        sign_package(package)  # staging has no private key at all
    assert exc.value.code == "SIGNING_KEY_MISSING"

    attacker_private, _ = generate_keypair()
    same_id = _forge(package, attacker_private, PROD_KEY_ID)
    assert _preview(client, admin, same_id, code=422)["error"]["code"] == "PACKAGE_SIGNATURE_INVALID"
    own_id = _forge(package, attacker_private, "staging-made")
    assert _preview(client, admin, own_id, code=422)["error"]["code"] == "PACKAGE_KEY_UNKNOWN"
    assert _ids() == {}


def _mutations(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    service = package["services"][0]

    def with_service(**changes: Any) -> dict[str, Any]:
        return {"services": [service | changes, *package["services"][1:]]}

    return {
        "uuid": with_service(id=str(uuid.uuid4())),
        "w_id": with_service(w_id="W999"),
        "status": with_service(status="active"),
        "version": with_service(version=service["version"] + 1),
        "links": {"service_qualifications": []},
        "package_id": {"package_id": str(uuid.uuid4())},
        "exported_at": {"exported_at": datetime.now(UTC).isoformat()},
        "role": {"catalogue_role": "isolated"},
    }


def test_signature_covers_the_whole_package(client: TestClient, admin: dict[str, str], role: Any) -> None:
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    role("receiver")
    assert package["service_qualifications"], "fixture must contain a requirement link"
    for name, change in _mutations(package).items():
        resp = client.post(f"{BASE}/sync-imports", json=package | change, headers=admin)
        assert resp.status_code == 422, name
        assert resp.json()["error"]["code"] == "PACKAGE_SIGNATURE_INVALID", name
    _, second_public = generate_keypair()
    role("receiver", trusted={PROD_KEY_ID: PROD_PUBLIC, "prod-test-2": second_public})
    swapped_key = package | {"key_id": "prod-test-2"}
    assert _preview(client, admin, swapped_key, code=422)["error"]["code"] == "PACKAGE_SIGNATURE_INVALID"


def test_key_rotation_and_revocation(client: TestClient, admin: dict[str, str], role: Any) -> None:
    _production_catalogue(client, admin)
    old = _export(client, admin, role)
    new_private, new_public = generate_keypair()
    rotated = _forge(
        old | {"package_id": str(uuid.uuid4())}, new_private, "prod-test-2"
    )  # production after switch
    both = {PROD_KEY_ID: PROD_PUBLIC, "prod-test-2": new_public}

    role("receiver", trusted=both)
    assert _preview(client, admin, old)["status"] == "previewed"
    assert _preview(client, admin, rotated)["status"] == "previewed"
    role("receiver", trusted=both, revoked=[PROD_KEY_ID])
    assert _preview(client, admin, old, code=422)["error"]["code"] == "PACKAGE_KEY_REVOKED"
    assert _preview(client, admin, rotated)["status"] == "previewed"


def test_replayed_and_outdated_packages_are_refused(
    client: TestClient, admin: dict[str, str], role: Any
) -> None:
    _production_catalogue(client, admin)
    older = _export(client, admin, role)
    newer = _resign(older, role, minutes=5)
    _wipe_catalogue()
    role("receiver")
    _apply(client, admin, _preview(client, admin, newer)["id"])
    assert _preview(client, admin, newer, code=409)["error"]["code"] == "PACKAGE_ALREADY_APPLIED"
    assert _preview(client, admin, older, code=409)["error"]["code"] == "PACKAGE_OUTDATED"
    # A legitimately signed, newer package that reuses an applied package ID is still a replay.
    role("issuer")
    later = (datetime.fromisoformat(newer["exported_at"]) + timedelta(minutes=10)).isoformat()
    replay = sign_package(newer | {"exported_at": later})
    role("receiver")
    assert _preview(client, admin, replay, code=409)["error"]["code"] == "PACKAGE_ALREADY_APPLIED"


def test_private_key_never_leaves_production(
    client: TestClient, admin: dict[str, str], role: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _production_catalogue(client, admin)
    package = _export(client, admin, role)
    role("receiver")
    _apply(client, admin, _preview(client, admin, package)["id"])
    role("issuer")
    settings = get_settings()
    secret_fragment = PROD_PRIVATE[:24]
    assert secret_fragment not in json.dumps(package)
    assert secret_fragment not in repr(settings) and secret_fragment not in str(settings.model_dump())
    assert secret_fragment not in caplog.text
    with SessionLocal() as db:
        rows = [*db.scalars(select(AuditLog)), *db.scalars(select(DomainEvent))]
        stored = json.dumps(
            [getattr(r, "after", None) or getattr(r, "payload", None) for r in rows], default=str
        )
    assert secret_fragment not in stored
    assert package["key_id"] == PROD_KEY_ID and set(package) >= {"package_id", "signature", "key_id"}
