import os
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuditLog, CatalogueCategory, CatalogueService, CatalogueSpecialisation
from app.seed.catalogue_cm_v1 import CATEGORIES
from app.services.catalogue_seed import SeedError, seed_catalogue, seed_id
from tests.conftest import auth

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "CATALOGUE_SEED.md")


def _parse_doc() -> list[dict[str, Any]]:
    """Independent reading of docs/CATALOGUE_SEED.md, the owner-approved source of the seed."""
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    notes: dict[str, str] = {}
    for line in doc.split("## Admin review flags")[1].split("\n## ")[0].splitlines():
        m = re.match(r"\| (W\d{3}(?:, W\d{3})*) \| (.+) \|$", line)
        if m:
            notes.update(dict.fromkeys(m.group(1).split(", "), m.group(2)))
    categories = []
    for block in re.split(r"\n## Category \d+ — ", doc)[1:]:
        status, ref = re.search(r"Category status: `(\w+)`.*`source_ref` `([\w-]+)`", block).groups()  # type: ignore[union-attr]
        specs = []
        for sb in re.split(r"\n### \d+\. ", block)[1:]:
            m = re.search(
                r'status: `(\w+)` · description \(verbatim\): "(.+?)" · `source_ref` `([\w-]+)`', sb
            )
            assert m
            services = [
                {
                    "w_id": w,
                    "ref": r,
                    "name": n,
                    "qualification_required": q == "yes",
                    "review_note": notes.get(w),
                }
                for w, n, q, r in re.findall(r"^\| (W\d{3}) \| (.+?) \| (yes|no) \| `([\w-]+)` \|$", sb, re.M)
            ]
            specs.append(
                {
                    "ref": m.group(3),
                    "name": sb.splitlines()[0].strip(),
                    "description": m.group(2),
                    "status": m.group(1),
                    "services": services,
                }
            )
        categories.append(
            {"ref": ref, "name": block.splitlines()[0].strip(), "status": status, "specialisations": specs}
        )
    return categories


def _all_services() -> list[dict[str, Any]]:
    return [s for c in CATEGORIES for sp in c["specialisations"] for s in sp["services"]]


def test_seed_data_matches_approved_document() -> None:
    assert _parse_doc() == CATEGORIES


def test_seed_data_shape() -> None:
    services = _all_services()
    assert len(CATEGORIES) == 3
    assert sum(len(c["specialisations"]) for c in CATEGORIES) == 24
    assert [s["w_id"] for s in services] == [f"W{n:03d}" for n in range(71, 143)]
    assert len({s["ref"] for s in services}) == 72
    regulated = {s["w_id"] for s in services if s["qualification_required"]}
    assert regulated == {"W103", "W104", "W105", "W112", "W113", "W114", "W115", "W128", "W129", "W130"}
    assert {s["w_id"] for s in services if s["review_note"]} == {"W077", "W101", "W131", "W132"}
    names = {s["w_id"]: s["name"] for s in services}
    assert names["W071"] == "Tualetes poda uzstādīšana"
    assert names["W101"] == "Izlietnes uzstādīšana vannas istabā"


def test_seed_inserts_approved_catalogue_as_drafts() -> None:
    with SessionLocal() as db:
        result = seed_catalogue(db)
        assert (result.categories, result.specialisations, result.services) == (3, 24, 72)
        services = db.scalars(select(CatalogueService).order_by(CatalogueService.w_id)).all()
        assert {s.status for s in services} == {"draft"}
        assert {s.source for s in services} == {"seed_cm_v1"}
        assert services[0].id == seed_id("cm-s01-1") and services[0].w_id == "W071"
        assert db.scalar(select(func.count()).where(CatalogueSpecialisation.qualification_required)) == 0
        statuses = {c.source_ref: c.status for c in db.scalars(select(CatalogueCategory))}
        assert statuses == {"cm-c1": "active", "cm-c2": "planned", "cm-c3": "planned"}
        assert db.scalar(select(func.count()).where(CatalogueCategory.description.is_not(None))) == 0
        assert (
            db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "catalogue.seeded"))
            == 1
        )


def test_seed_is_idempotent_and_keeps_admin_edits() -> None:
    with SessionLocal() as db:
        seed_catalogue(db)
        service = db.get(CatalogueService, seed_id("cm-s01-1"))
        assert service is not None
        service.name = "Edited by admin"
        db.commit()
        again = seed_catalogue(db)
        assert again.total == 0
        db.refresh(service)
        assert service.name == "Edited by admin"
        assert db.scalar(select(func.count()).select_from(CatalogueService)) == 72


def test_next_admin_service_after_seed_is_w143(client: TestClient, admin_token: str) -> None:
    with SessionLocal() as db:
        seed_catalogue(db)
    spec_id = str(seed_id("cm-s01"))
    resp = client.post(
        "/api/v1/admin/catalogue/services",
        json={"specialisation_id": spec_id, "name": "Jauns pakalpojums"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["w_id"] == "W143"


def test_seed_aborts_without_writing_when_w_id_is_taken() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO catalogue_categories (id, name, status) "
                "VALUES (gen_random_uuid(), 'X', 'inactive')"
            )
        )
        db.execute(
            text(
                "INSERT INTO catalogue_specialisations (id, category_id, name, status) "
                "SELECT gen_random_uuid(), id, 'Y', 'inactive' FROM catalogue_categories"
            )
        )
        db.execute(
            text(
                "INSERT INTO catalogue_services (id, specialisation_id, w_id, name, status) "
                "SELECT gen_random_uuid(), id, 'W080', 'Z', 'inactive' FROM catalogue_specialisations"
            )
        )
        db.commit()
        with pytest.raises(SeedError, match="W080"):
            seed_catalogue(db)
        assert db.scalar(select(func.count()).select_from(CatalogueService)) == 1


def test_staging_refuses_to_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "catalogue_role", "receiver")
    with SessionLocal() as db, pytest.raises(SeedError, match="Staging"):
        seed_catalogue(db)
