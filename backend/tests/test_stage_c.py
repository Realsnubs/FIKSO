"""Stage C: commercial terms, public catalogue, public images, content (C1–C4, C6)."""

import io
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AuditLog, CatalogueService, CommercialTerms
from tests.conftest import auth, register
from tests.factories import Catalogue, build_catalogue, make_master


@pytest.fixture
def cat() -> Catalogue:
    return build_catalogue()


def _jpeg(width: int = 1600, height: int = 1000, gps: bool = True) -> bytes:
    image = Image.new("RGB", (width, height), (200, 120, 40))
    buffer = io.BytesIO()
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {2: (56.0, 57.0, 0.0), 4: (24.0, 6.0, 0.0)}  # GPSInfo
        exif[0x010F] = "SecretCam"
    image.save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


# ---------------------------------------------------------------- C1 commercial terms


def test_public_terms_have_the_approved_values_and_fall_back_to_latvian(client: TestClient) -> None:
    body = client.get("/api/v1/public/commercial-terms?lang=ru").json()
    assert body["hourly_rate_eur"] == "40.00" and body["minimum_order_eur"] == "40.00"
    assert body["materials_note"] == "Материалы и расходные материалы оплачиваются отдельно."


def test_terms_change_is_a_new_row_with_history_and_audit(client: TestClient, admin_token: str) -> None:
    resp = client.post(
        "/api/v1/admin/commercial-terms",
        json={
            "hourly_rate_eur": "45.00",
            "minimum_order_eur": "45.00",
            "materials_note": {"lv": "Materiāli atsevišķi."},
            "reason": "Jauni noteikumi",
        },
        headers=auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    history = client.get("/api/v1/admin/commercial-terms", headers=auth(admin_token)).json()
    assert [h["hourly_rate_eur"] for h in history] == ["45.00", "40.00"]
    public = client.get("/api/v1/public/commercial-terms?lang=en").json()
    assert public["hourly_rate_eur"] == "45.00"
    assert public["materials_note_lang"] == "lv"  # no English text given: Latvian, never auto-translated
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "commercial_terms.changed")) is not None
        assert db.query(CommercialTerms).count() == 2


def test_terms_admin_api_is_admin_only(client: TestClient) -> None:
    token = register(client, "client")["access_token"]
    assert client.get("/api/v1/admin/commercial-terms", headers=auth(token)).status_code == 403
    assert client.post("/api/v1/admin/commercial-terms", json={}).status_code == 401


# ---------------------------------------------------------------- C2 public catalogue


def test_catalogue_lists_only_orderable_services_and_planned_specialisations(
    client: TestClient, cat: Catalogue
) -> None:
    empty = client.get("/api/v1/public/catalogue").json()
    names = [s["name"]["lv"] for c in empty["categories"] for s in c["specialisations"]]
    assert names == ["Logu meistars"]  # no eligible master yet: only the planned one ("Drīzumā")
    make_master(client, cat, services=(cat.service,))
    body = client.get("/api/v1/public/catalogue").json()
    specs = {s["name"]["lv"]: s for c in body["categories"] for s in c["specialisations"]}
    assert specs["Logu meistars"]["status"] == "planned" and specs["Logu meistars"]["services"] == []
    services = specs["Gaismekļu meistars"]["services"]
    assert [s["w_id"] for s in services] == ["W092"]  # W093 has no master, W094 is a draft
    text = str(body)
    for internal in ("restrictions", "review_note", "eligible_masters", "Meistars"):
        assert internal not in text


def test_w_id_resolves_only_orderable_services_with_one_neutral_error(
    client: TestClient, cat: Catalogue
) -> None:
    make_master(client, cat)
    assert client.get("/api/v1/public/services/by-w-id/w092").json()["service"]["w_id"] == "W092"
    for w_id in ("W094", "W999"):
        resp = client.get(f"/api/v1/public/services/by-w-id/{w_id}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PUBLIC_SERVICE_NOT_AVAILABLE"
        assert resp.json()["error"]["message"] == "This service is currently unavailable."


def test_hold_service_never_becomes_public(client: TestClient, cat: Catalogue) -> None:
    make_master(client, cat)
    with SessionLocal() as db:
        db.get(CatalogueService, cat.service).status = "hold"  # type: ignore[union-attr]
        db.commit()
    assert client.get("/api/v1/public/services/by-w-id/W092").status_code == 404


# ---------------------------------------------------------------- C3 images


def _upload(client: TestClient, token: str, data: bytes, **form: str) -> object:
    fields = {"rights_basis": "own", "personal_data_checked": "true", "alt_lv": "Gaismeklis", **form}
    return client.post(
        "/api/v1/admin/media", files={"file": ("x.jpg", data, "image/jpeg")}, data=fields, headers=auth(token)
    )


def test_image_upload_makes_webp_variants_without_metadata(client: TestClient, admin_token: str) -> None:
    resp = _upload(client, admin_token, _jpeg())
    assert resp.status_code == 201, resp.text  # type: ignore[attr-defined]
    body = resp.json()  # type: ignore[attr-defined]
    assert set(body["urls"]) == {"560", "800", "1300"}
    served = client.get(body["urls"]["800"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    image = Image.open(io.BytesIO(served.content))
    assert image.size == (800, 500)
    assert not image.getexif() and b"SecretCam" not in served.content


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"%PDF-1.4 not an image", "INVALID_IMAGE"), (_jpeg(600, 400), "IMAGE_TOO_SMALL")],
)
def test_bad_images_are_rejected(client: TestClient, admin_token: str, data: bytes, code: str) -> None:
    resp = _upload(client, admin_token, data)
    assert resp.json()["error"]["code"] == code  # type: ignore[attr-defined]


def test_rights_and_personal_data_check_are_required(client: TestClient, admin_token: str) -> None:
    assert (
        _upload(client, admin_token, _jpeg(), personal_data_checked="false").json()["error"]["code"]
        == "PERSONAL_DATA_NOT_CHECKED"
    )  # type: ignore[attr-defined]
    assert (
        _upload(client, admin_token, _jpeg(), rights_basis="client_consent").json()["error"]["code"]
        == "CONSENT_REQUIRED"
    )  # type: ignore[attr-defined]


def test_withdrawn_consent_unpublishes_everywhere(client: TestClient, admin_token: str) -> None:
    body = _upload(
        client,
        admin_token,
        _jpeg(),
        rights_basis="client_consent",
        rights_reference="Līgums 12",
        consent_given_on="2026-10-01",
    ).json()  # type: ignore[attr-defined]
    url = body["urls"]["560"]
    assert client.get(url).status_code == 200
    resp = client.post(
        f"/api/v1/admin/media/{body['id']}/withdraw-consent",
        json={"reason": "Klients atsauca"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 200 and resp.json()["consent_withdrawn_at"]
    assert client.get(url).status_code == 404


def test_media_upload_is_admin_only(client: TestClient) -> None:
    token = register(client, "master")["access_token"]
    assert _upload(client, token, _jpeg()).status_code == 403  # type: ignore[attr-defined]


# ---------------------------------------------------------------- C4 / C6 content


def _content(client: TestClient, token: str, spec: uuid.UUID) -> dict:  # type: ignore[type-arg]
    return client.get(f"/api/v1/admin/content/{spec}", headers=auth(token)).json()


def test_draft_publish_and_public_page(client: TestClient, admin_token: str, cat: Catalogue) -> None:
    make_master(client, cat)
    media_id = _upload(client, admin_token, _jpeg()).json()["id"]  # type: ignore[attr-defined]
    page = _content(client, admin_token, cat.spec)
    assert page["slug"] == "gaismeklu-meistars" and page["draft"] is None
    data = {
        "locales": {
            "lv": {
                "title": "Gaismekļu uzstādīšana Rīgā",
                "lead": "Ātri un droši.",
                "faq": [{"q": "Cik ilgi?", "a": "Stundu."}],
            },
            "en": {"title": "Light fitting in Riga", "name": "Light fitter"},
        },
        "card_image": media_id,
        "gallery": [{"media_id": media_id, "kind": "after", "caption": {"lv": "Gatavs"}}],
        "services": {str(cat.service): {"lv": "Uzstādām gaismekli.", "en": "We fit the light."}},
    }
    saved = client.put(
        f"/api/v1/admin/content/{cat.spec}/draft",
        json={"data": data, "expected_version": page["version"]},
        headers=auth(admin_token),
    )
    assert saved.status_code == 200, saved.text
    assert (
        client.get("/api/v1/public/specialisations/gaismeklu-meistars").json()["texts"] == {}
    )  # draft is not public
    published = client.post(
        f"/api/v1/admin/content/{cat.spec}/publish",
        json={"expected_version": saved.json()["version"]},
        headers=auth(admin_token),
    )
    assert published.status_code == 200, published.text
    public = client.get("/api/v1/public/specialisations/gaismeklu-meistars").json()
    assert public["texts"]["lv"]["title"] == "Gaismekļu uzstādīšana Rīgā"
    assert public["name"] == {"lv": "Gaismekļu meistars", "en": "Light fitter"}
    assert [s["w_id"] for s in public["services"]] == ["W092", "W093"]
    assert public["services"][0]["description"]["en"] == "We fit the light."
    assert len(public["gallery"]) == 1 and public["card_image"]["urls"]["800"]
    assert public["terms"]["materials_note"]["lv"].startswith("Materiāli")


def test_stale_version_conflicts(client: TestClient, admin_token: str, cat: Catalogue) -> None:
    resp = client.put(
        f"/api/v1/admin/content/{cat.spec}/draft",
        json={"data": {}, "expected_version": 99},
        headers=auth(admin_token),
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "VERSION_CONFLICT"


def test_limits_and_foreign_services_are_rejected(
    client: TestClient, admin_token: str, cat: Catalogue
) -> None:
    v = _content(client, admin_token, cat.spec)["version"]
    long_title = {"locales": {"lv": {"title": "x" * 121}}}
    assert (
        client.put(
            f"/api/v1/admin/content/{cat.spec}/draft",
            json={"data": long_title, "expected_version": v},
            headers=auth(admin_token),
        ).status_code
        == 422
    )
    foreign = {"services": {str(uuid.uuid4()): {"lv": "x"}}}
    resp = client.put(
        f"/api/v1/admin/content/{cat.spec}/draft",
        json={"data": foreign, "expected_version": v},
        headers=auth(admin_token),
    )
    assert resp.json()["error"]["code"] == "CONTENT_INVALID"


def test_slug_change_redirects_the_old_address(client: TestClient, admin_token: str, cat: Catalogue) -> None:
    make_master(client, cat)
    v = _content(client, admin_token, cat.spec)["version"]
    assert (
        client.put(
            f"/api/v1/admin/content/{cat.spec}/slug",
            json={"slug": "gaismekli", "expected_version": v},
            headers=auth(admin_token),
        ).status_code
        == 200
    )
    resp = client.get("/api/v1/public/specialisations/gaismeklu-meistars", follow_redirects=False)
    assert resp.status_code == 308 and resp.headers["location"].endswith("/gaismekli")
    assert client.get("/api/v1/public/specialisations/gaismekli").json()["slug"] == "gaismekli"


def test_page_of_a_specialisation_without_orderable_services_is_hidden(
    client: TestClient, admin_token: str, cat: Catalogue
) -> None:
    _content(client, admin_token, cat.spec)
    assert client.get("/api/v1/public/specialisations/gaismeklu-meistars").status_code == 404


def test_content_admin_is_admin_only(client: TestClient, cat: Catalogue) -> None:
    token = register(client, "client")["access_token"]
    assert client.get("/api/v1/admin/content", headers=auth(token)).status_code == 403


def test_public_events_are_counted_anonymously(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/public/events", json={"event_type": "catalogue_view", "source": "web"}
        ).status_code
        == 204
    )
    assert client.post("/api/v1/public/events", json={"event_type": "hack"}).status_code == 422


def test_money_rules() -> None:
    from app.services.money import commission, labour_amount

    rate, minimum = Decimal("40.00"), Decimal("40.00")
    assert labour_amount(rate, minimum, 3600) == Decimal("40.00")  # A: 1 h
    assert labour_amount(rate, minimum, 1800) == Decimal("40.00")  # B: 30 min → minimum
    assert labour_amount(rate, minimum, 7200) == Decimal("80.00")  # C: 2 h
    assert commission(Decimal("0.25"), Decimal("40.00")) == Decimal("10.00")
    assert commission(Decimal("0.25"), Decimal("80.00")) == Decimal("20.00")
    assert labour_amount(rate, minimum, 5430) == Decimal("60.33")  # 1 h 30 min 30 s, ROUND_HALF_UP


def test_planned_specialisations_of_a_planned_category_are_coming_soon(
    client: TestClient, cat: Catalogue
) -> None:
    """Regression (browser QA): planned specialisations live in planned categories and are listed."""
    from app.models import CatalogueCategory, CatalogueSpecialisation

    with SessionLocal() as db:
        planned_cat = CatalogueCategory(name="Specializētie meistari", status="planned")
        db.add(planned_cat)
        db.flush()
        db.add(CatalogueSpecialisation(name="Durvju meistars", status="planned", category_id=planned_cat.id))
        db.commit()
    body = client.get("/api/v1/public/catalogue").json()
    planned = {
        s["name"]["lv"]: s
        for c in body["categories"]
        for s in c["specialisations"]
        if s["status"] == "planned"
    }
    assert planned["Durvju meistars"]["services"] == []


def test_a_page_without_content_has_a_readable_slug(client: TestClient, cat: Catalogue) -> None:
    """Regression (browser QA): the card link and the page address use the Latvian slug, not the UUID."""
    make_master(client, cat)
    body = client.get("/api/v1/public/catalogue").json()
    spec = next(s for c in body["categories"] for s in c["specialisations"] if s["status"] == "active")
    assert spec["slug"] == "gaismeklu-meistars"
    assert (
        client.get("/api/v1/public/specialisations/gaismeklu-meistars").json()["name"]["lv"]
        == "Gaismekļu meistars"
    )
