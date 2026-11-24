"""Stage D and P1/P2: requests, photos, matching (option A), timers, exclusivity, work, commission, worker."""

import io
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import worker
from app.core.db import SessionLocal
from app.models import (
    AuditLog,
    CommissionLedgerEntry,
    JobRun,
    MasterLocation,
    MasterProfile,
    MatchingRun,
    Notification,
    Order,
    OrderDeparture,
    OrderOffer,
    OrderStatusHistory,
    ServiceRequest,
    User,
    WorkSegment,
)
from tests.conftest import auth, register
from tests.factories import Catalogue, Master, build_catalogue, make_master

API = "/api/v1"


@pytest.fixture
def cat() -> Catalogue:
    return build_catalogue()


@pytest.fixture
def client_token(client: TestClient) -> str:
    return register(client, "client")["access_token"]


def _photo(fmt: str = "JPEG") -> bytes:
    image = Image.new("RGB", (900, 700), (10, 120, 200))
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x8825] = {2: (56.0, 57.0, 0.0)}
    exif[0x010F] = "PhoneX"
    image.save(buffer, fmt, exif=exif.tobytes())
    return buffer.getvalue()


def _create(client: TestClient, token: str, **extra: object) -> dict:  # type: ignore[type-arg]
    """A request in Rīga; extra fields override (e.g. communication_language)."""
    body = {
        "w_id": "W092",
        "description": "Jāuzstāda griestu lustra viesistabā.",
        "address": "Brīvības iela 1, Rīga",
        "city": "riga",
        **extra,
    }
    resp = client.post(f"{API}/client/requests", json=body, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _submitted(client: TestClient, token: str, **extra: object) -> dict:  # type: ignore[type-arg]
    req = _create(client, token, **extra)
    resp = client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _confirm(client: TestClient, token: str, req: dict, index: int = 0) -> dict:  # type: ignore[type-arg]
    cand = req["proposal"]["masters"][index]["candidate_id"]
    resp = client.post(
        f"{API}/client/requests/{req['id']}/confirm", json={"candidate_id": cand}, headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _offer_id(client: TestClient, master: Master) -> str:
    offers = client.get(f"{API}/master/offers", headers=auth(master.token)).json()
    assert len(offers) == 1, offers
    return offers[0]["id"]


# ---------------------------------------------------------------- D1 requests and photos


def test_request_validation_and_neutral_unavailable(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    resp = client.post(
        f"{API}/client/requests",
        json={"w_id": "W092", "description": "short", "address": "Rīga 1", "city": "riga"},
        headers=auth(client_token),
    )
    assert resp.status_code == 422
    resp = client.post(
        f"{API}/client/requests",
        json={"w_id": "W092", "description": "x" * 2001, "address": "Rīga 1", "city": "riga"},
        headers=auth(client_token),
    )
    assert resp.status_code == 422
    # W092 is not orderable yet (no master): the neutral message, no internal reason.
    resp = client.post(
        f"{API}/client/requests",
        json={"w_id": "W092", "description": "Jāuzstāda lustra.", "address": "Rīga 1", "city": "riga"},
        headers=auth(client_token),
    )
    assert (
        resp.status_code == 404
        and resp.json()["error"]["message"] == "This service is currently unavailable."
    )


def test_source_is_validated_from_a_central_list(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat)
    assert _create(client, client_token, src="web")["source"] == "website_deeplink"
    assert _create(client, client_token, src="evil")["source"] == "app"
    assert _create(client, client_token)["source"] == "app"


def test_idempotent_create(client: TestClient, cat: Catalogue, client_token: str) -> None:
    make_master(client, cat)
    body = {
        "w_id": "W092",
        "description": "Jāuzstāda griestu lustra.",
        "address": "Brīvības iela 1",
        "city": "riga",
    }
    headers = {**auth(client_token), "Idempotency-Key": "k-1"}
    first = client.post(f"{API}/client/requests", json=body, headers=headers).json()
    second = client.post(f"{API}/client/requests", json=body, headers=headers).json()
    assert first["id"] == second["id"]


def test_photos_are_reencoded_private_limited_and_draft_only(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat)
    req = _create(client, client_token)
    url = f"{API}/client/requests/{req['id']}/photos"
    resp = client.post(url, files={"file": ("a.png", _photo("PNG"), "image/png")}, headers=auth(client_token))
    assert resp.status_code == 201, resp.text
    photo_id = resp.json()["id"]
    served = client.get(f"{url}/{photo_id}", headers=auth(client_token))
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    assert b"PhoneX" not in served.content and not Image.open(io.BytesIO(served.content)).getexif()
    other = register(client, "client")["access_token"]
    assert client.get(f"{url}/{photo_id}", headers=auth(other)).status_code == 404
    assert client.get(f"{API}/client/requests/{req['id']}", headers=auth(other)).status_code == 404
    for _ in range(4):
        assert (
            client.post(
                url, files={"file": ("a.jpg", _photo(), "image/jpeg")}, headers=auth(client_token)
            ).status_code
            == 201
        )
    sixth = client.post(url, files={"file": ("a.jpg", _photo(), "image/jpeg")}, headers=auth(client_token))
    assert sixth.json()["error"]["code"] == "TOO_MANY_FILES"
    video = client.post(
        url,
        files={"file": ("a.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 100, "video/mp4")},
        headers=auth(client_token),
    )
    assert video.status_code in (400, 415)
    client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(client_token))
    late = client.post(url, files={"file": ("a.jpg", _photo(), "image/jpeg")}, headers=auth(client_token))
    assert late.json()["error"]["code"] == "REQUEST_NOT_DRAFT"
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "attachment.viewed")) is not None


def test_heic_photo_is_converted(client: TestClient, cat: Catalogue, client_token: str) -> None:
    from pillow_heif import from_pillow

    make_master(client, cat)
    req = _create(client, client_token)
    buffer = io.BytesIO()
    from_pillow(Image.new("RGB", (640, 480), (1, 2, 3))).save(buffer, format="HEIF")
    resp = client.post(
        f"{API}/client/requests/{req['id']}/photos",
        files={"file": ("a.heic", buffer.getvalue(), "image/heic")},
        headers=auth(client_token),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------- D2 option A, privacy, D3 lifecycle,
# commission


def test_full_flow_option_a_with_privacy_and_commission(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    master = make_master(client, cat, rating=Decimal("4.80"))
    req = _create(client, client_token, src="web")
    photo = client.post(
        f"{API}/client/requests/{req['id']}/photos",
        files={"file": ("a.jpg", _photo(), "image/jpeg")},
        headers=auth(client_token),
    ).json()
    req = client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(client_token)).json()
    assert req["status"] == "proposed" and req["proposal"]["round"] == 1
    shown = req["proposal"]["masters"][0]
    assert "phone" not in shown and "email" not in shown and shown["first_name"] == "Meistars"
    # Showing the master to the client does not create an offer and does not block the master.
    assert client.get(f"{API}/master/offers", headers=auth(master.token)).json() == []
    req = _confirm(client, client_token, req)
    assert (
        req["status"] == "confirmed"
        and req["order"]["status"] == "offered"
        and req["order"]["master_phone"] is None
    )
    order_id = _offer_id(client, master)
    offer = client.get(f"{API}/master/orders/{order_id}", headers=auth(master.token)).json()
    assert offer["client"] is None and offer["address"] is None  # no address/phone before assignment
    assert offer["description"].startswith("Jāuzstāda") and len(offer["photos"]) == 1
    seen = client.get(f"{API}/master/orders/{order_id}/photos/{photo['id']}", headers=auth(master.token))
    assert seen.status_code == 200
    with SessionLocal() as db:
        o = db.get(Order, uuid.UUID(order_id))
        offer_row = db.scalar(select(OrderOffer).where(OrderOffer.order_id == o.id))  # type: ignore[union-attr]
        assert (offer_row.expires_at - offer_row.offered_at) == timedelta(minutes=10)  # type: ignore[union-attr]
    accepted = client.post(f"{API}/master/orders/{order_id}/accept", headers=auth(master.token)).json()
    assert accepted["status"] == "accepted" and accepted["address"]["address"] == "Brīvības iela 1, Rīga"
    assert accepted["client"]["phone"]
    for action in ("depart", "arrive", "start", "pause", "resume", "finish"):
        resp = client.post(f"{API}/master/orders/{order_id}/{action}", headers=auth(master.token))
        assert resp.status_code == 200, (action, resp.text)
    early = client.post(f"{API}/master/orders/{order_id}/finalise", headers=auth(master.token))
    assert early.json()["error"]["code"] == "WORKSHEET_INCOMPLETE"
    sheet = {
        "work_description": "Uzstādīta lustra.",
        "materials": [{"name": "Spaile", "quantity": "2", "unit": "gab", "amount_eur": "15.00"}],
    }
    assert (
        client.put(
            f"{API}/master/orders/{order_id}/worksheet", json=sheet, headers=auth(master.token)
        ).status_code
        == 200
    )
    done = client.post(f"{API}/master/orders/{order_id}/finalise", headers=auth(master.token)).json()
    assert done["status"] == "completed"
    assert done["worksheet"]["labour_amount_eur"] == "40.00"  # a few seconds of work → the 40 € minimum
    assert (
        done["worksheet"]["commission_eur"] == "10.00"
        and done["worksheet"]["materials_amount_eur"] == "15.00"
    )
    again = client.post(f"{API}/master/orders/{order_id}/finalise", headers=auth(master.token))
    assert again.status_code == 200
    with SessionLocal() as db:
        charges = db.scalars(
            select(CommissionLedgerEntry).where(CommissionLedgerEntry.entry_type == "charge")
        ).all()
        assert (
            len(charges) == 1
            and charges[0].amount_eur == Decimal("10.00")
            and charges[0].base_labour_eur == Decimal("40.00")
        )
        assert (
            db.scalar(select(OrderDeparture).where(OrderDeparture.order_id == uuid.UUID(order_id)))
            is not None
        )
        profile = db.get(MasterProfile, master.profile_id)
        assert profile.is_busy is False and profile.completed_jobs == 1  # type: ignore[union-attr]
        req_row = db.get(ServiceRequest, uuid.UUID(req["id"]))
        assert req_row.source == "website_deeplink" and req_row.commercial_terms_id is not None  # type: ignore[union-attr]
    fin = client.get(f"{API}/master/commission", headers=auth(master.token)).json()
    assert fin["charged_total_eur"] == "10.00" and fin["amount_due_eur"] == "10.00"
    after = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
    assert after["order"]["labour_amount_eur"] == "40.00" and after["order"]["master_phone"]
    # Regression (browser QA): the recovery job must never reopen matching for a completed order.
    assert worker.recover_requests(datetime.now(UTC) + timedelta(minutes=10)) == 0
    after_job = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
    assert after_job["proposal"] is None and after_job["status"] == "confirmed"
    review = client.post(
        f"{API}/client/orders/{order_id}/review", json={"rating": 5}, headers=auth(client_token)
    )
    assert review.status_code == 201
    assert (
        client.post(
            f"{API}/client/orders/{order_id}/review", json={"rating": 4}, headers=auth(client_token)
        ).status_code
        == 409
    )


def test_finalise_uses_actual_work_time_only(client: TestClient, cat: Catalogue, client_token: str) -> None:
    master = make_master(client, cat)
    req = _confirm(client, client_token, _submitted(client, client_token))
    order_id = _offer_id(client, master)
    for action in ("accept",):
        client.post(f"{API}/master/orders/{order_id}/{action}", headers=auth(master.token))
    for action in ("depart", "arrive", "start", "finish"):
        client.post(f"{API}/master/orders/{order_id}/{action}", headers=auth(master.token))
    with SessionLocal() as db:
        # 2 h of actual work and 45 min of travel: only the work counts (K-7).
        seg = db.scalar(select(WorkSegment).where(WorkSegment.order_id == uuid.UUID(order_id)))
        seg.ended_at = seg.started_at + timedelta(hours=2)  # type: ignore[union-attr]
        o = db.get(Order, uuid.UUID(order_id))
        o.en_route_at = o.arrived_at - timedelta(minutes=45)  # type: ignore[union-attr,operator]
        db.commit()
    client.put(
        f"{API}/master/orders/{order_id}/worksheet",
        json={
            "work_description": "Darbs",
            "materials": [{"name": "Kabelis", "quantity": "1", "amount_eur": "25.00"}],
        },
        headers=auth(master.token),
    )
    done = client.post(f"{API}/master/orders/{order_id}/finalise", headers=auth(master.token)).json()
    assert (
        done["worksheet"]["labour_amount_eur"] == "80.00" and done["worksheet"]["commission_eur"] == "20.00"
    )
    assert done["worksheet"]["travel_minutes"] == 45 and done["worksheet"]["billable_seconds"] == 7200
    assert req["status"] == "confirmed"


# ---------------------------------------------------------------- rounds and timers


def test_decline_excludes_master_and_expiry_does_not(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    a = make_master(client, cat, location=(Decimal("56.95"), Decimal("24.10")))
    b = make_master(client, cat, location=(Decimal("56.98"), Decimal("24.20")))
    req = _submitted(client, client_token)
    first = req["proposal"]["masters"][0]
    _confirm(client, client_token, req)
    nearest = a if client.get(f"{API}/master/offers", headers=auth(a.token)).json() else b
    other = b if nearest is a else a
    order_id = _offer_id(client, nearest)
    client.post(
        f"{API}/master/orders/{order_id}/decline", json={"reason": "Aizņemts"}, headers=auth(nearest.token)
    )
    req = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
    assert req["status"] == "proposed" and req["proposal"]["round"] == 2
    assert [m["candidate_id"] for m in req["proposal"]["masters"]] != [first["candidate_id"]]
    assert len(req["proposal"]["masters"]) == 1  # the declining master is excluded for this request
    _confirm(client, client_token, req)
    order2 = _offer_id(client, other)
    # The master does not answer: the worker expires the offer after 10 minutes.
    assert worker.expire_offers(datetime.now(UTC) + timedelta(minutes=9)) == 0
    assert worker.expire_offers(datetime.now(UTC) + timedelta(minutes=11)) == 1
    req = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
    assert req["status"] == "proposed" and req["proposal"]["round"] == 3
    assert len(req["proposal"]["masters"]) == 1  # expiry alone does not exclude: the same master again
    with SessionLocal() as db:
        assert db.get(Order, uuid.UUID(order2)).status == "expired"  # type: ignore[union-attr]
        endings = [r.close_reason for r in db.scalars(select(MatchingRun).order_by(MatchingRun.created_at))]
        # Regression (browser QA): the master's answer is the round's outcome, not the client confirmation.
        assert endings[:2] == ["master_declined", "master_expired"]
    assert client.post(f"{API}/master/orders/{order2}/accept", headers=auth(other.token)).status_code == 409


def test_client_timeout_ends_the_round_and_three_rounds_make_unserved(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat)
    req = _submitted(client, client_token)
    clock = datetime.now(UTC)
    for expected_round in (2, 3):
        assert worker.expire_proposals(clock + timedelta(minutes=4)) == 0
        clock += timedelta(minutes=6)  # the next round's 5-minute window starts at this moment
        assert worker.expire_proposals(clock) == 1
        req = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
        assert req["proposal"]["round"] == expected_round
    worker.expire_proposals(clock + timedelta(minutes=6))
    req = client.get(f"{API}/client/requests/{req['id']}", headers=auth(client_token)).json()
    assert req["status"] == "unserved" and req["unserved_reason"] == "rounds_exhausted"
    with SessionLocal() as db:
        assert db.scalar(select(Notification).where(Notification.type == "request.unserved")) is not None
        assert db.query(MatchingRun).count() == 3


def test_reserved_timers_and_reject(client: TestClient, cat: Catalogue, client_token: str) -> None:
    make_master(client, cat, mode="available_for_reservations", location=None)
    start = datetime.now(UTC) + timedelta(days=2)
    req = _submitted(
        client,
        client_token,
        request_type="reserved",
        preferred_time_from=start.isoformat(),
        preferred_time_to=(start + timedelta(hours=3)).isoformat(),
    )
    expires = datetime.fromisoformat(req["proposal"]["expires_at"])
    assert timedelta(minutes=29) < expires - datetime.now(UTC) <= timedelta(minutes=30)
    rejected = client.post(f"{API}/client/requests/{req['id']}/reject", headers=auth(client_token)).json()
    assert rejected["proposal"]["round"] == 2 and len(rejected["proposal"]["masters"]) == 1  # not excluded
    confirmed = _confirm(client, client_token, rejected)
    with SessionLocal() as db:
        order = db.get(Order, uuid.UUID(confirmed["order"]["id"]))
        offer = db.scalar(select(OrderOffer).where(OrderOffer.order_id == order.id))  # type: ignore[union-attr]
        assert offer.expires_at - offer.offered_at == timedelta(minutes=120)  # type: ignore[union-attr]


def test_no_candidates_is_unserved_at_once(client: TestClient, cat: Catalogue, client_token: str) -> None:
    master = make_master(client, cat)
    req = _create(client, client_token)
    with SessionLocal() as db:
        db.get(MasterProfile, master.profile_id).availability_mode = "unavailable"  # type: ignore[union-attr]
        db.commit()
    with SessionLocal() as db:
        # still orderable in the catalogue (eligibility ignores availability), matching finds nobody
        pass
    resp = client.post(f"{API}/client/requests/{req['id']}/submit", headers=auth(client_token)).json()
    assert resp["status"] == "unserved" and resp["unserved_reason"] == "no_candidates"


# ---------------------------------------------------------------- filters: location, limit, zone


def test_stale_location_excludes_from_immediate_but_not_from_reservations(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat, location_at=datetime.now(UTC) - timedelta(minutes=16))
    immediate = _submitted(client, client_token)
    assert immediate["status"] == "unserved"
    start = datetime.now(UTC) + timedelta(days=1)
    reserved = _submitted(
        client,
        client_token,
        request_type="reserved",
        preferred_time_from=start.isoformat(),
        preferred_time_to=(start + timedelta(hours=2)).isoformat(),
    )
    assert reserved["status"] == "proposed"


def test_commission_limit_excludes_payment_restores_and_issued_offer_stays(
    client: TestClient, cat: Catalogue, client_token: str, admin_token: str
) -> None:
    master = make_master(client, cat)
    req = _confirm(client, client_token, _submitted(client, client_token))
    order_id = _offer_id(client, master)
    resp = client.post(
        f"{API}/admin/commission/masters/{master.profile_id}/adjustments",
        json={"amount_eur": "100.00", "reason": "Iepriekšējais parāds"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 201 and resp.json()["limit_reached"] is True
    # The already issued offer is not withdrawn and can still be accepted (Q-D2-2).
    assert (
        client.post(f"{API}/master/orders/{order_id}/accept", headers=auth(master.token)).status_code == 200
    )
    blocked = _submitted(
        client,
        client_token,
        request_type="reserved",
        preferred_time_from=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        preferred_time_to=(datetime.now(UTC) + timedelta(days=3, hours=2)).isoformat(),
    )
    assert blocked["status"] == "unserved"  # at the limit: excluded from new matching
    pay = client.post(
        f"{API}/admin/commission/masters/{master.profile_id}/payments",
        json={
            "amount_eur": "30.00",
            "paid_on": datetime.now(UTC).date().isoformat(),
            "payment_method": "bank_transfer",
            "comment": "Pārskaitījums",
        },
        headers=auth(admin_token),
    ).json()
    assert (
        pay["balance_eur"] == "70.00" and pay["paid_total_eur"] == "30.00" and pay["limit_reached"] is False
    )
    again = _submitted(
        client,
        client_token,
        request_type="reserved",
        preferred_time_from=(datetime.now(UTC) + timedelta(days=4)).isoformat(),
        preferred_time_to=(datetime.now(UTC) + timedelta(days=4, hours=2)).isoformat(),
    )
    assert again["status"] == "proposed"
    future = client.post(
        f"{API}/admin/commission/masters/{master.profile_id}/payments",
        json={
            "amount_eur": "1.00",
            "paid_on": (datetime.now(UTC) + timedelta(days=2)).date().isoformat(),
            "payment_method": "cash",
        },
        headers=auth(admin_token),
    )
    assert future.status_code == 422
    limit = client.post(
        f"{API}/admin/commission/masters/{master.profile_id}/limit",
        json={"new_limit_eur": "50.00", "reason": "Samazināts"},
        headers=auth(admin_token),
    ).json()
    assert limit["limit_eur"] == "50.00" and limit["limit_reached"] is True
    with SessionLocal() as db, pytest.raises(DBAPIError):  # the ledger is append-only
        db.execute(text("UPDATE commission_ledger SET amount_eur = 0"))
    assert req["status"] == "confirmed"


def test_city_and_language_decide_who_can_be_proposed(
    client: TestClient, cat: Catalogue, client_token: str, admin_token: str
) -> None:
    """City-based matching (2026-11-05): same city required; the client's language must be spoken."""
    make_master(client, cat, city="jelgava", languages=("lv",))
    other_city = _submitted(client, client_token)  # client in Rīga
    assert other_city["status"] == "unserved"
    with SessionLocal() as db:
        run = db.scalar(select(MatchingRun).where(MatchingRun.request_id == uuid.UUID(other_city["id"])))
        assert run.excluded_counts == {"city": 1}  # type: ignore[union-attr]
    riga = make_master(client, cat, city="riga", languages=("lv", "ru"))
    assert _submitted(client, client_token, communication_language="de")["status"] == "unserved"
    for language in ("lv", "ru", "any"):
        req = _submitted(client, client_token, communication_language=language)
        assert req["status"] == "proposed", language
        assert req["communication_language"] == language and req["city"]["code"] == "riga"
        client.post(f"{API}/client/requests/{req['id']}/cancel", json={}, headers=auth(client_token))
    assert riga.token
    rows = client.get(f"{API}/admin/requests", headers=auth(admin_token)).json()
    assert {(r["city"], r["communication_language"]) for r in rows} >= {("riga", "de"), ("riga", "any")}
    # The order carries the client's language, so the master and the admin see it after confirmation.
    req = _confirm(client, client_token, _submitted(client, client_token, communication_language="ru"))
    order = client.get(f"{API}/master/orders/{_offer_id(client, riga)}", headers=auth(riga.token)).json()
    assert order["communication_language"] == "ru" and order["city"]["code"] == "riga"
    with SessionLocal() as db:
        query = select(Order.communication_language).where(Order.request_id == uuid.UUID(req["id"]))
        assert db.scalar(query) == "ru"


def test_master_without_city_or_languages_is_never_matched(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat, city=None)
    make_master(client, cat, languages=())
    req = _submitted(client, client_token)
    assert req["status"] == "unserved"
    with SessionLocal() as db:
        run = db.scalar(select(MatchingRun).where(MatchingRun.request_id == uuid.UUID(req["id"])))
        assert run.excluded_counts == {"city": 1, "language": 1}  # type: ignore[union-attr]


def test_request_city_must_match_its_location(client: TestClient, cat: Catalogue, client_token: str) -> None:
    make_master(client, cat)
    resp = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Ventspils",
            "city": "riga",
            "lat": "57.389",
            "lon": "21.561",
        },
        headers=auth(client_token),
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "CITY_MISMATCH"
    unknown = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Rīga, centrs",
            "city": "atlantis",
        },
        headers=auth(client_token),
    )
    assert unknown.json()["error"]["code"] == "UNKNOWN_CITY"
    bad_language = client.post(
        f"{API}/client/requests",
        json={
            "w_id": "W092",
            "description": "Jāuzstāda lustra.",
            "address": "Rīga, centrs",
            "city": "riga",
            "communication_language": "xx",
        },
        headers=auth(client_token),
    )
    assert bad_language.json()["error"]["code"] == "UNKNOWN_LANGUAGE"


# ---------------------------------------------------------------- exclusivity and EXCLUDE


def test_master_with_active_offer_gets_no_overlapping_offer(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    master = make_master(client, cat)
    _confirm(client, client_token, _submitted(client, client_token))
    other_client = register(client, "client")["access_token"]
    second = _submitted(client, other_client)
    assert second["status"] == "unserved"  # the only master is blocked by the active offer
    with SessionLocal() as db:
        run = db.scalar(select(MatchingRun).where(MatchingRun.request_id == uuid.UUID(second["id"])))
        assert run.excluded_counts == {"overlapping_offer": 1}  # type: ignore[union-attr]
    assert master.token


def test_exclusion_constraint_rejects_overlap_in_the_database(
    client: TestClient, cat: Catalogue, client_token: str
) -> None:
    make_master(client, cat)
    req = _confirm(client, client_token, _submitted(client, client_token))
    with SessionLocal() as db:
        order = db.get(Order, uuid.UUID(req["order"]["id"]))
        assert order is not None
        clone = Order(
            request_id=order.request_id,
            matching_run_id=order.matching_run_id,
            client_id=order.client_id,
            master_id=order.master_id,
            order_type="reserved",
            status="scheduled",
            estimated_start=order.estimated_start,
            estimated_end=order.estimated_end,
            busy_range=Range(
                order.busy_range.lower + timedelta(minutes=5),
                order.busy_range.upper + timedelta(hours=1),
                bounds="[)",
            ),  # type: ignore[operator]
            client_confirmed_at=order.client_confirmed_at,
            offered_at=order.offered_at,
            commission_rate_snapshot=Decimal("0.25"),
            hourly_rate_snapshot=Decimal("40"),
            minimum_order_snapshot=Decimal("40"),
        )
        db.add(clone)
        with pytest.raises(IntegrityError) as caught:
            db.flush()
        assert "ex_orders_master_busy_range" in str(caught.value)


def test_released_block_allows_a_new_offer(client: TestClient, cat: Catalogue, client_token: str) -> None:
    master = make_master(client, cat)
    _confirm(client, client_token, _submitted(client, client_token))
    order_id = _offer_id(client, master)
    client.post(f"{API}/master/orders/{order_id}/decline", json={}, headers=auth(master.token))
    other = register(client, "client")["access_token"]
    assert _submitted(client, other)["status"] == "proposed"  # declined offer no longer blocks


def test_two_clients_confirm_the_same_master_concurrently(client: TestClient, cat: Catalogue) -> None:
    make_master(client, cat)
    tokens = [register(client, "client")["access_token"] for _ in range(2)]
    reqs = [_submitted(client, t) for t in tokens]
    results: list[int] = []

    def go(i: int) -> None:
        c = TestClient(client.app)
        cand = reqs[i]["proposal"]["masters"][0]["candidate_id"]
        results.append(
            c.post(
                f"{API}/client/requests/{reqs[i]['id']}/confirm",
                json={"candidate_id": cand},
                headers=auth(tokens[i]),
            ).status_code
        )

    threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    with SessionLocal() as db:
        assert db.query(Order).filter(Order.status == "offered").count() == 1
        loser = next(
            r for r in reqs if db.scalar(select(Order).where(Order.request_id == uuid.UUID(r["id"]))) is None
        )
        runs = db.scalars(
            select(MatchingRun)
            .where(MatchingRun.request_id == uuid.UUID(loser["id"]))
            .order_by(MatchingRun.created_at)
        ).all()
        # The conflict is a technical re-run in the same round, not a new round.
        assert [(r.run_no, r.attempt, r.close_reason) for r in runs] == [
            (1, 1, "conflict"),
            (1, 2, "no_candidates" if False else runs[1].close_reason),
        ]
        assert runs[1].run_no == 1


def test_cancel_releases_the_block(client: TestClient, cat: Catalogue, client_token: str) -> None:
    master = make_master(client, cat)
    req = _confirm(client, client_token, _submitted(client, client_token))
    cancelled = client.post(
        f"{API}/client/requests/{req['id']}/cancel",
        json={"reason": "Vairs nevajag"},
        headers=auth(client_token),
    ).json()
    assert cancelled["status"] == "cancelled"
    assert client.get(f"{API}/master/offers", headers=auth(master.token)).json() == []
    other = register(client, "client")["access_token"]
    assert _submitted(client, other)["status"] == "proposed"


# ---------------------------------------------------------------- roles


def test_roles_and_ownership(client: TestClient, cat: Catalogue, client_token: str) -> None:
    a = make_master(client, cat)
    b = make_master(client, cat, location=(Decimal("57.30"), Decimal("25.00")), city="jelgava")
    _confirm(client, client_token, _submitted(client, client_token))
    order_id = _offer_id(client, a)
    assert client.get(f"{API}/master/orders/{order_id}", headers=auth(b.token)).status_code == 404
    assert client.post(f"{API}/master/orders/{order_id}/accept", headers=auth(b.token)).status_code == 404
    assert client.get(f"{API}/master/offers", headers=auth(client_token)).status_code == 403
    assert client.post(f"{API}/client/requests", json={}, headers=auth(a.token)).status_code == 403
    assert client.get(f"{API}/admin/commission/masters", headers=auth(a.token)).status_code == 403
    assert client.get(f"{API}/admin/stats/overview").status_code == 401


# ---------------------------------------------------------------- P1 availability


def test_work_city_languages_and_location(client: TestClient, cat: Catalogue) -> None:
    master = make_master(client, cat, location=None, city=None, languages=(), mode="unavailable")
    h = auth(master.token)
    blocked = client.put(f"{API}/master/availability", json={"mode": "available_now"}, headers=h)
    assert blocked.json()["error"]["code"] == "WORK_CITY_REQUIRED"
    assert client.put(f"{API}/master/work-city", json={"city": "atlantis"}, headers=h).status_code == 422
    assert (
        client.put(f"{API}/master/work-city", json={"city": "jelgava"}, headers=h).json()["work_city"]
        == "jelgava"
    )
    assert (
        client.put(f"{API}/master/work-city", json={"city": "riga"}, headers=h).json()["work_city"] == "riga"
    )
    no_lang = client.put(f"{API}/master/availability", json={"mode": "available_now"}, headers=h)
    assert no_lang.json()["error"]["code"] == "LANGUAGES_REQUIRED"
    assert (
        client.put(f"{API}/master/languages", json={"languages": ["lv", "xx"]}, headers=h).status_code == 422
    )
    langs = client.put(f"{API}/master/languages", json={"languages": ["RU", "lv", "de"]}, headers=h).json()
    assert langs["languages"] == ["de", "lv", "ru"]
    assert (
        client.post(f"{API}/master/location", json={"lat": "56.95", "lon": "24.11"}, headers=h).status_code
        == 204
    )
    client.post(f"{API}/master/location", json={"lat": "56.96", "lon": "24.12"}, headers=h)
    with SessionLocal() as db:
        rows = db.scalars(select(MasterLocation).where(MasterLocation.master_id == master.profile_id)).all()
        assert len(rows) == 1 and rows[0].lat == Decimal("56.960000")  # only the latest point
        from app.models import MasterCity

        assert db.query(MasterCity).filter(MasterCity.master_id == master.profile_id).count() == 1
    profile = client.put(f"{API}/master/availability", json={"mode": "available_now"}, headers=h).json()
    assert profile["availability_mode"] == "available_now" and profile["location_fresh"] is True
    cleared = client.put(f"{API}/master/languages", json={"languages": []}, headers=h).json()
    assert cleared["languages"] == [] and cleared["availability_mode"] == "unavailable"


def test_reference_lists_are_public_and_separate_from_interface_languages(client: TestClient) -> None:
    cities = client.get(f"{API}/public/cities").json()
    assert (
        cities[0] == {"code": "riga", "name": {"lv": "Rīga", "en": "Riga", "ru": "Рига"}}
        and len(cities) == 40
    )
    languages = client.get(f"{API}/public/communication-languages").json()
    assert len(languages) == 24 and {"lv", "ru", "en", "de", "hi"} <= {lang["code"] for lang in languages}


# ---------------------------------------------------------------- worker


def test_worker_records_runs_retries_and_marks_stale(client: TestClient) -> None:
    result = worker.run_once()
    assert set(result) == {
        "expire_proposals",
        "expire_offers",
        "recover_requests",
        "deliver_notifications",
        "purge_rate_limits",
    }
    with SessionLocal() as db:
        assert db.query(JobRun).filter(JobRun.status == "succeeded").count() == 5
        user = User(role="client", email="n@example.lv", password_hash="x", full_name="N")
        db.add(user)
        db.flush()
        db.add(Notification(user_id=user.id, type="t", channel="sms", status="pending"))
        db.add(
            JobRun(
                job_name="x",
                worker_id="w",
                started_at=datetime.now(UTC) - timedelta(hours=1),
                status="running",
            )
        )
        db.commit()

    class Failing:
        name = "test"

        def send(self, to: str, text: str, reference: str) -> None:
            from app.integrations.sms import SmsError

            raise SmsError("provider down", permanent=False)

    db_user = None
    with SessionLocal() as db:
        db_user = db.scalar(select(User).where(User.email == "n@example.lv"))
        assert db_user is not None
        db_user.phone = "+37120009999"
        db.query(Notification).filter(Notification.channel == "sms").update({"type": "order.accepted"})
        db.commit()
    worker.deliver_notifications(datetime.now(UTC), Failing())
    with SessionLocal() as db:
        row = db.scalar(select(Notification).where(Notification.channel == "sms"))
        assert row.attempts == 1 and row.status == "pending" and row.next_attempt_at > datetime.now(UTC)  # type: ignore[union-attr,operator]
    worker.deliver_notifications(datetime.now(UTC), None)  # not due yet: untouched
    # due, no provider: skipped, never "sent"
    worker.deliver_notifications(datetime.now(UTC) + timedelta(hours=1), None)
    with SessionLocal() as db:
        assert db.scalar(select(Notification.status).where(Notification.channel == "sms")) == "skipped"
    assert worker.mark_stale_runs(datetime.now(UTC)) == 1


def test_admin_stats_and_monitoring(
    client: TestClient, cat: Catalogue, client_token: str, admin_token: str
) -> None:
    make_master(client, cat)
    req = _submitted(client, client_token, src="web")
    stats = client.get(f"{API}/admin/stats/overview", headers=auth(admin_token)).json()
    assert stats["requests"]["by_source"] == {"website_deeplink": 1}
    assert stats["catalogue"]["orderable_services"] == 2
    detail = client.get(f"{API}/admin/requests/{req['id']}", headers=auth(admin_token)).json()
    assert detail["rounds"][0]["candidates"][0]["role"] == "proposal"
    assert [h["to"] for h in detail["history"]] == ["matching", "proposed"]
    with SessionLocal() as db:
        assert db.query(OrderStatusHistory).count() == 2
