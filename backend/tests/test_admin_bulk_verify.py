"""Bulk competency verification (step 4.4.8, R-MST-14, Q-28, owner decisions 2026-11-02): preview, then all or
nothing; non-regulated services only; one audit entry and one event per verified competency."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.business_time import business_today
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models import (
    AuditLog,
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
from app.models.catalogue import service_qualifications
from app.schemas.admin_masters import BULK_VERIFY_MAX as SCHEMA_MAX
from app.services import eligibility, master_admin
from app.services import master_capabilities as svc
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import auth, register

SPEC = seed_id("cm-s01")
PLAIN = [seed_id(f"cm-s01-{n}") for n in (1, 2, 3)]  # non-regulated, same specialisation
REGULATED = seed_id("cm-s01-4")  # gets a qualification requirement in the fixture
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
PREVIEW = "/api/v1/admin/masters/{}/competencies/bulk-verify/preview"
APPLY = "/api/v1/admin/masters/{}/competencies/bulk-verify"


@dataclass
class M:
    id: uuid.UUID
    user_id: uuid.UUID
    h: dict[str, str]


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        seed_catalogue(db)
        db.execute(
            update(CatalogueService)
            .where(CatalogueService.id.in_([*PLAIN, REGULATED]))
            .values(status="inactive")
        )
        qualification = Qualification(name="Elektrodrošība", status="active")
        db.add(qualification)
        db.flush()
        db.execute(
            service_qualifications.insert().values(service_id=REGULATED, qualification_id=qualification.id)
        )
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, qualification.id)


def _decided(fx: Fx) -> dict[str, Any]:
    return {"decided_by": fx.admin_id, "decided_at": T0}


def _master(
    client: TestClient, fx: Fx, services: tuple[uuid.UUID, ...] = (*PLAIN, REGULATED), *, spec: bool = True
) -> M:
    """Approved profile and specialisation, declared competencies for `services`, a valid qualification."""
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
        assert master_id is not None
        db.execute(
            update(MasterProfile)
            .where(MasterProfile.id == master_id)
            .values(approval_status="approved", **_decided(fx))
        )
        if spec:
            db.add(
                MasterSpecialisation(
                    master_id=master_id, specialisation_id=SPEC, status="approved", **_decided(fx)
                )
            )
        db.add(
            MasterQualification(
                master_id=master_id,
                qualification_id=fx.qualification_id,
                status="verified",
                valid_until=business_today(db) + timedelta(days=100),
                **_decided(fx),
            )
        )
        for service_id in services:
            db.add(MasterCompetency(master_id=master_id, service_id=service_id))
        db.commit()
    return M(master_id, user_id, auth(body["access_token"]))


def _preview(client: TestClient, fx: Fx, master_id: Any, service_ids: list[Any]) -> Any:
    return client.post(
        PREVIEW.format(master_id), json={"service_ids": [str(s) for s in service_ids]}, headers=fx.admin
    )


def _apply(
    client: TestClient, fx: Fx, master_id: Any, items: list[tuple[Any, int]], confirm: Any = True
) -> Any:
    body = {"items": [{"service_id": str(s), "expected_version": v} for s, v in items], "confirm": confirm}
    return client.post(APPLY.format(master_id), json=body, headers=fx.admin)


def _state() -> tuple[Any, ...]:
    """Every master and catalogue row that a decision could touch, plus all audit entries and events."""
    with SessionLocal() as db:
        rows = [
            tuple(sorted((c.key, getattr(row, c.key)) for c in model.__table__.columns))
            for model in (
                MasterProfile,
                MasterSpecialisation,
                MasterCompetency,
                MasterQualification,
                User,
                CatalogueService,
                CatalogueSpecialisation,
            )
            for row in db.scalars(select(model))
        ]
        return (
            sorted(rows, key=repr),
            db.scalar(select(func.count()).select_from(AuditLog)),
            db.scalar(select(func.count()).select_from(DomainEvent)),
        )


def _statuses(master: M) -> dict[uuid.UUID, tuple[str, int]]:
    with SessionLocal() as db:
        return {
            r.service_id: (r.status, r.version)
            for r in db.scalars(select(MasterCompetency).where(MasterCompetency.master_id == master.id))
        }


def _set(model: Any, where: Any, **values: Any) -> None:
    with SessionLocal() as db:
        db.execute(update(model).where(where).values(**values))
        db.commit()


def _failures(resp: Any) -> dict[str, list[str]]:
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "BULK_VERIFY_REJECTED"
    return {item["service_id"]: [r["code"] for r in item["reasons"]] for item in error["details"]["items"]}


def _competency_log(master: M) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action == "master.competency.verified", AuditLog.entity_id == master.id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def test_limit_is_shared_by_schema_and_service() -> None:
    assert SCHEMA_MAX == master_admin.BULK_VERIFY_MAX == 50


# --- access -------------------------------------------------------------------------------------------------


def test_only_admins(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    customer = auth(register(client, "client")["access_token"])
    before = _state()
    requests = [
        (PREVIEW.format(master.id), {"service_ids": [str(PLAIN[0])]}),
        (
            APPLY.format(master.id),
            {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1}], "confirm": True},
        ),
    ]
    for url, body in requests:
        assert client.post(url, json=body).status_code == 401
        assert (
            client.post(url, json=body, headers=master.h).status_code == 403
        )  # not on their own competencies
        assert client.post(url, json=body, headers=customer).status_code == 403
    assert _state() == before


# --- preview ------------------------------------------------------------------------------------------------


def test_preview_lists_each_selected_item_and_writes_nothing(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    before = _state()
    resp = _preview(client, fx, master.id, PLAIN)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applicable"] is True
    assert [i["service_id"] for i in body["items"]] == [str(s) for s in PLAIN]  # as selected, nothing added
    for item in body["items"]:
        assert (item["status"], item["expected_version"], item["verifiable"], item["reasons"]) == (
            "declared",
            1,
            True,
            [],
        )
        assert item["w_id"] and item["name"]
    assert _state() == before


def test_preview_reports_every_reason_per_item(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    other = _master(client, fx, services=(PLAIN[2],))
    _set(
        MasterCompetency,
        (MasterCompetency.master_id == master.id) & (MasterCompetency.service_id == PLAIN[1]),
        status="verified",
        **_decided(fx),
    )
    _set(CatalogueService, CatalogueService.id == PLAIN[2], status="draft")
    with SessionLocal() as db:  # PLAIN[2] declared by `other` only
        db.execute(
            update(MasterCompetency)
            .where(MasterCompetency.master_id == master.id, MasterCompetency.service_id == PLAIN[2])
            .values(status="withdrawn")
        )
        db.commit()
    unknown = uuid.uuid4()
    before = _state()
    body = _preview(client, fx, master.id, [PLAIN[0], PLAIN[1], PLAIN[2], REGULATED, unknown]).json()
    assert body["applicable"] is False
    got = {i["service_id"]: (i["verifiable"], [r["code"] for r in i["reasons"]]) for i in body["items"]}
    assert got == {
        str(PLAIN[0]): (True, []),
        str(PLAIN[1]): (False, ["INVALID_TRANSITION"]),
        str(PLAIN[2]): (False, ["INVALID_TRANSITION", "SERVICE_NOT_AVAILABLE"]),
        str(REGULATED): (False, ["REGULATED_SERVICE"]),  # even with the qualification held
        str(unknown): (False, ["COMPETENCY_NOT_FOUND"]),
    }
    unknown_item = next(i for i in body["items"] if i["service_id"] == str(unknown))
    assert (unknown_item["status"], unknown_item["expected_version"], unknown_item["w_id"]) == (
        None,
        None,
        None,
    )
    assert _state() == before
    assert other.id != master.id


@pytest.mark.parametrize(
    ("case", "codes"),
    [
        ("profile_pending", ["PROFILE_NOT_APPROVED"]),
        ("profile_rejected", ["PROFILE_NOT_APPROVED"]),
        ("specialisation_requested", ["SPECIALISATION_NOT_APPROVED"]),
        ("specialisation_missing", ["SPECIALISATION_NOT_APPROVED"]),
        ("service_regulated", ["REGULATED_SERVICE", "QUALIFICATION_NOT_CONFIGURED"]),
        ("specialisation_regulated", ["REGULATED_SERVICE", "QUALIFICATION_NOT_CONFIGURED"]),
        ("service_archived", ["SERVICE_NOT_AVAILABLE"]),
        ("service_rejected", ["SERVICE_NOT_AVAILABLE"]),
    ],
)
def test_preview_conditions(client: TestClient, fx: Fx, case: str, codes: list[str]) -> None:
    master = _master(client, fx, spec=case != "specialisation_missing")
    match case:
        case "profile_pending":
            _set(MasterProfile, MasterProfile.id == master.id, approval_status="pending_approval")
        case "profile_rejected":
            _set(MasterProfile, MasterProfile.id == master.id, approval_status="rejected")
        case "specialisation_requested":
            _set(MasterSpecialisation, MasterSpecialisation.master_id == master.id, status="requested")
        case "service_regulated":
            _set(CatalogueService, CatalogueService.id == PLAIN[0], qualification_required=True)
        case "specialisation_regulated":
            _set(CatalogueSpecialisation, CatalogueSpecialisation.id == SPEC, qualification_required=True)
        case "service_archived" | "service_rejected":
            _set(CatalogueService, CatalogueService.id == PLAIN[0], status=case.removeprefix("service_"))
    before = _state()
    [item] = _preview(client, fx, master.id, [PLAIN[0]]).json()["items"]
    assert (item["verifiable"], [r["code"] for r in item["reasons"]]) == (False, codes)
    assert _state() == before


@pytest.mark.parametrize(
    "body",
    [
        {"service_ids": []},
        {"service_ids": [str(PLAIN[0]), str(PLAIN[0])]},
        {"service_ids": [str(uuid.uuid4()) for _ in range(51)]},
        {"service_ids": ["x"]},
        {},
        {"service_ids": [str(PLAIN[0])], "all": True},  # no "select everything"
    ],
)
def test_preview_input(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client, fx)
    assert client.post(PREVIEW.format(master.id), json=body, headers=fx.admin).status_code == 422


def test_preview_of_unknown_or_deleted_master(client: TestClient, fx: Fx) -> None:
    master, gone = _master(client, fx), _master(client, fx)
    _set(User, User.id == gone.user_id, deleted_at=T0)
    for target in (uuid.uuid4(), master.user_id, gone.id):
        resp = _preview(client, fx, target, [PLAIN[0]])
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "MASTER_NOT_FOUND")


# --- apply --------------------------------------------------------------------------------------------------


def test_apply_verifies_every_listed_item_with_its_own_audit_and_event(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    preview = _preview(client, fx, master.id, PLAIN).json()
    items = [(i["service_id"], i["expected_version"]) for i in preview["items"]]
    resp = _apply(client, fx, master.id, items)
    assert resp.status_code == 200, resp.text
    competencies = {c["service_id"]: c for c in resp.json()["competencies"]}
    for service_id in PLAIN:
        out = competencies[str(service_id)]
        assert (out["status"], out["version"], out["decided_by"], out["decision_reason"]) == (
            "verified",
            2,
            str(fx.admin_id),
            None,
        )
        assert out["eligible"] is True
    assert competencies[str(REGULATED)]["status"] == "declared"  # not selected, not touched
    log = _competency_log(master)
    assert sorted(e.after["service_id"] for e in log if e.after) == sorted(str(s) for s in PLAIN)
    for entry in log:
        assert (
            entry.actor_id == fx.admin_id
            and entry.before is not None
            and entry.before["status"] == "declared"
        )
    with SessionLocal() as db:
        events = db.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "master.competency.verified")
        ).all()
        assert sorted(e.payload["service_id"] for e in events) == sorted(str(s) for s in PLAIN)
        for service_id in PLAIN:
            assert eligibility.eligible_master_ids(db, service_id) == [master.id]
        # Nothing else changed: specialisation, services and the user stay as they were.
        assert db.scalar(
            select(MasterSpecialisation.status).where(MasterSpecialisation.master_id == master.id)
        ) == ("approved")
        assert set(db.scalars(select(CatalogueService.status).where(CatalogueService.id.in_(PLAIN)))) == {
            "inactive"
        }


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1}], "confirm": False},
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1}]},
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1}], "confirm": "true"},
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1}], "confirm": 1},
        {"items": [], "confirm": True},
        {"confirm": True},
        {
            "items": [
                {"service_id": str(PLAIN[0]), "expected_version": 1},
                {"service_id": str(PLAIN[0]), "expected_version": 1},
            ],
            "confirm": True,
        },
        {
            "items": [{"service_id": str(uuid.uuid4()), "expected_version": 1} for _ in range(51)],
            "confirm": True,
        },
        {"items": [{"service_id": str(PLAIN[0])}], "confirm": True},
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 0}], "confirm": True},
        {"items": [{"service_id": str(PLAIN[0]), "expected_version": 1, "reason": "x"}], "confirm": True},
        {
            "items": [{"service_id": str(PLAIN[0]), "expected_version": 1}],
            "confirm": True,
            "status": "verified",
        },
    ],
)
def test_apply_input(client: TestClient, fx: Fx, body: dict[str, Any]) -> None:
    master = _master(client, fx)
    before = _state()
    assert client.post(APPLY.format(master.id), json=body, headers=fx.admin).status_code == 422
    assert _state() == before


def test_apply_accepts_exactly_the_limit(client: TestClient, fx: Fx) -> None:
    """50 items pass validation (and fail as unknown competencies, all reported, nothing written)."""
    master = _master(client, fx)
    before = _state()
    items = [(uuid.uuid4(), 1) for _ in range(49)] + [(PLAIN[0], 1)]
    failures = _failures(_apply(client, fx, master.id, items))
    assert len(failures) == 49 and set(map(tuple, failures.values())) == {("COMPETENCY_NOT_FOUND",)}
    assert _state() == before


@pytest.mark.parametrize(
    ("case", "bad", "codes"),
    [
        ("stale_version", PLAIN[1], ["VERSION_CONFLICT"]),
        ("already_verified", PLAIN[1], ["VERSION_CONFLICT"]),
        ("regulated", REGULATED, ["REGULATED_SERVICE"]),
        ("not_eligible", PLAIN[2], ["SERVICE_NOT_AVAILABLE"]),
        ("unknown", None, ["COMPETENCY_NOT_FOUND"]),
        ("other_masters", PLAIN[2], ["COMPETENCY_NOT_FOUND"]),
    ],
)
def test_all_or_nothing(client: TestClient, fx: Fx, case: str, bad: Any, codes: list[str]) -> None:
    """Three selected, one fails: none is verified, and no audit entry or event appears."""
    services = (*PLAIN, REGULATED) if case != "other_masters" else (PLAIN[0], PLAIN[1])
    master = _master(client, fx, services=services)
    items = [(PLAIN[0], 1), (PLAIN[1], 1), (PLAIN[2], 1)]
    match case:
        case "stale_version":
            _set(
                MasterCompetency,
                (MasterCompetency.master_id == master.id) & (MasterCompetency.service_id == bad),
                version=4,
            )
        case "already_verified":
            _set(
                MasterCompetency,
                (MasterCompetency.master_id == master.id) & (MasterCompetency.service_id == bad),
                status="verified",
                version=2,
                **_decided(fx),
            )
        case "regulated":
            items[2] = (REGULATED, 1)
        case "not_eligible":
            _set(CatalogueService, CatalogueService.id == bad, status="archived")
        case "unknown":
            bad = uuid.uuid4()
            items[2] = (bad, 1)
        case "other_masters":
            _master(client, fx, services=(PLAIN[2],))  # another master declared it; this one did not
    before = _state()
    failures = _failures(_apply(client, fx, master.id, items))
    assert failures == {str(bad): codes}
    assert _state() == before
    assert all(status != "verified" or case == "already_verified" for status, _ in _statuses(master).values())


def test_stale_version_details_show_the_current_state(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _set(
        MasterCompetency,
        (MasterCompetency.master_id == master.id) & (MasterCompetency.service_id == PLAIN[0]),
        version=3,
    )
    error = _apply(client, fx, master.id, [(PLAIN[0], 1)]).json()["error"]
    assert error["details"]["items"] == [
        {
            "service_id": str(PLAIN[0]),
            "reasons": [{"code": "VERSION_CONFLICT", "details": {"status": "declared", "version": 3}}],
        }
    ]


def test_every_failing_item_is_reported(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    _set(MasterProfile, MasterProfile.id == master.id, approval_status="pending_approval")
    failures = _failures(_apply(client, fx, master.id, [(PLAIN[0], 1), (REGULATED, 1)]))
    assert failures == {
        str(PLAIN[0]): ["PROFILE_NOT_APPROVED"],
        str(REGULATED): ["REGULATED_SERVICE", "PROFILE_NOT_APPROVED"],
    }


def test_change_between_preview_and_apply(client: TestClient, fx: Fx) -> None:
    master = _master(client, fx)
    preview = _preview(client, fx, master.id, PLAIN).json()
    assert preview["applicable"]
    with SessionLocal() as db:  # the master withdraws one item after the preview
        user = db.get(User, master.user_id)
        assert user is not None
        svc.withdraw_competency(db, user, PLAIN[1])
    before = _state()
    items = [(i["service_id"], i["expected_version"]) for i in preview["items"]]
    assert _failures(_apply(client, fx, master.id, items)) == {str(PLAIN[1]): ["VERSION_CONFLICT"]}
    assert _state() == before


def test_unknown_or_deleted_master(client: TestClient, fx: Fx) -> None:
    master, gone = _master(client, fx), _master(client, fx)
    _set(User, User.id == gone.user_id, deleted_at=T0)
    before = _state()
    for target in (uuid.uuid4(), master.user_id, gone.id):
        resp = _apply(client, fx, target, [(PLAIN[0], 1)])
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "MASTER_NOT_FOUND")
    assert _state() == before


def test_bulk_never_rejects_or_revokes(client: TestClient, fx: Fx) -> None:
    """Only verification exists in bulk: verified items in the list are refused, not revoked."""
    master = _master(client, fx)
    _set(
        MasterCompetency,
        (MasterCompetency.master_id == master.id) & (MasterCompetency.service_id == PLAIN[0]),
        status="verified",
        **_decided(fx),
    )
    assert _failures(_apply(client, fx, master.id, [(PLAIN[0], 1)])) == {
        str(PLAIN[0]): ["INVALID_TRANSITION"]
    }
    assert _statuses(master)[PLAIN[0]] == ("verified", 1)


@pytest.mark.parametrize("fail_at", [2, 3])
def test_a_write_error_rolls_back_every_decision(
    client: TestClient, fx: Fx, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    master = _master(client, fx)
    before = _state()
    real = master_admin.log_change
    calls = {"n": 0}

    def failing(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise RuntimeError("storage of the decision failed")
        real(*args, **kwargs)

    monkeypatch.setattr(master_admin, "log_change", failing)
    with pytest.raises(RuntimeError):
        _apply(client, fx, master.id, [(s, 1) for s in PLAIN])
    assert calls["n"] == fail_at
    assert _state() == before  # the first decision(s), already flushed, are rolled back too


# --- concurrency (PostgreSQL) -------------------------------------------------------------------------------


def _bulk(fx: Fx, master_id: uuid.UUID, items: list[tuple[uuid.UUID, int]]) -> None:
    with SessionLocal() as db:
        admin = db.get(User, fx.admin_id)
        assert admin is not None
        master_admin.bulk_verify(db, admin, master_id, items)


def _run(target: Any, results: list[str], *args: Any) -> None:
    try:
        target(*args)
        results.append("ok")
    except AppError as exc:
        results.append(exc.code)


@pytest.mark.parametrize(
    "held",
    ["specialisation_revoked", "competency_withdrawn", "competency_rejected_by_admin", "profile_rejected"],
)
def test_bulk_waits_for_the_master_row_lock(client: TestClient, fx: Fx, held: str) -> None:
    """A concurrent change under the master lock is seen by the re-check, never raced.

    Without `FOR UPDATE` on the master row the bulk reads the old state, passes and verifies everything
    although the specialisation was revoked (or an item withdrawn/rejected) at the same time: this fails.
    """
    master = _master(client, fx)
    outcome: list[str] = []
    with SessionLocal() as holder:
        holder.scalar(select(MasterProfile).where(MasterProfile.id == master.id).with_for_update())
        if held == "specialisation_revoked":
            holder.execute(
                update(MasterSpecialisation)
                .where(MasterSpecialisation.master_id == master.id)
                .values(status="revoked")
            )
        elif held == "profile_rejected":
            holder.execute(
                update(MasterProfile).where(MasterProfile.id == master.id).values(approval_status="rejected")
            )
        else:
            values: dict[str, Any] = {"status": "withdrawn", "version": 2}
            if held == "competency_rejected_by_admin":
                values = {"status": "rejected", "version": 2, "decision_reason": "Cits", **_decided(fx)}
            holder.execute(
                update(MasterCompetency)
                .where(MasterCompetency.master_id == master.id, MasterCompetency.service_id == PLAIN[1])
                .values(**values)
            )
        thread = threading.Thread(target=_run, args=(_bulk, outcome, fx, master.id, [(s, 1) for s in PLAIN]))
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the bulk verification must wait for the master row lock"
        holder.commit()
    thread.join(timeout=30)
    assert outcome == ["BULK_VERIFY_REJECTED"]
    assert all(status != "verified" for status, _ in _statuses(master).values())
    assert _competency_log(master) == []


def test_parallel_revocation_of_an_unrelated_qualification(client: TestClient, fx: Fx) -> None:
    """Non-regulated items do not depend on qualifications: both changes apply, one after the other."""
    master = _master(client, fx)
    with SessionLocal() as db:
        submission = db.scalar(
            select(MasterQualification.id).where(MasterQualification.master_id == master.id)
        )
    assert submission is not None
    barrier = threading.Barrier(2)
    results: dict[str, list[str]] = {"bulk": [], "revoke": []}

    def bulk() -> None:
        barrier.wait()
        _run(_bulk, results["bulk"], fx, master.id, [(s, 1) for s in PLAIN])

    def revoke() -> None:
        barrier.wait()
        with SessionLocal() as db:
            admin = db.get(User, fx.admin_id)
            assert admin is not None
            decision = master_admin.Decision("revoke", 1, "Viltots")
            _run(
                master_admin.decide_qualification,
                results["revoke"],
                db,
                admin,
                master.id,
                submission,
                decision,
            )

    threads = [threading.Thread(target=bulk), threading.Thread(target=revoke)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results == {"bulk": ["ok"], "revoke": ["ok"]}
    assert all(_statuses(master)[s][0] == "verified" for s in PLAIN)
    assert _statuses(master)[REGULATED] == ("declared", 1)


def test_parallel_bulk_and_single_decisions(client: TestClient, fx: Fx) -> None:
    """Overlapping bulk requests (opposite orders) and a single rejection: no deadlock, no partial result."""
    master = _master(client, fx)
    barrier = threading.Barrier(3)
    results: dict[str, list[str]] = {"forward": [], "backward": [], "reject": []}

    def bulk(name: str, items: list[tuple[uuid.UUID, int]]) -> None:
        barrier.wait()
        _run(_bulk, results[name], fx, master.id, items)

    def reject() -> None:
        barrier.wait()
        with SessionLocal() as db:
            admin = db.get(User, fx.admin_id)
            assert admin is not None
            decision = master_admin.Decision("reject", 1, "Nav pieredzes")
            _run(master_admin.decide_competency, results["reject"], db, admin, master.id, PLAIN[1], decision)

    threads = [
        threading.Thread(target=bulk, args=("forward", [(s, 1) for s in PLAIN])),
        threading.Thread(target=bulk, args=("backward", [(s, 1) for s in reversed(PLAIN)])),
        threading.Thread(target=reject),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    outcomes = [r for values in results.values() for r in values]
    assert outcomes.count("ok") == 1, results  # exactly one of the three wins; the others see its result
    assert set(outcomes) <= {"ok", "BULK_VERIFY_REJECTED", "VERSION_CONFLICT"}
    statuses = {s: _statuses(master)[s][0] for s in PLAIN}
    if results["reject"] == ["ok"]:
        assert statuses == {PLAIN[0]: "declared", PLAIN[1]: "rejected", PLAIN[2]: "declared"}
    else:
        assert set(statuses.values()) == {"verified"}
    with SessionLocal() as db:
        competency_events = db.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(DomainEvent.event_type.like("master.competency.%"))
        )
    assert competency_events == (1 if results["reject"] == ["ok"] else 3)
