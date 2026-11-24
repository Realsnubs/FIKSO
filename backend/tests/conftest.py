import os
import re
import uuid

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg:///fikso_test")
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["COOKIE_SECURE"] = "false"
# Uploaded test files go to a throw-away directory, never into the repository.
os.environ["STORAGE_LOCAL_DIR"] = __import__("tempfile").mkdtemp(prefix="fikso-test-uploads-")
os.environ["STORAGE_PUBLIC_DIR"] = __import__("tempfile").mkdtemp(prefix="fikso-test-public-")
os.environ["PUBLIC_CACHE_SECONDS"] = "0"
# One test process: the in-memory limiter keeps tests isolated; test_production covers the PostgreSQL one.
os.environ["RATE_LIMIT_BACKEND"] = "memory"

from collections.abc import Iterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.integrations.storage import get_storage  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CatalogueCategory, CatalogueService, CatalogueSpecialisation, Qualification, User  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
PASSWORD = "correct-horse-42"
# RESTART IDENTITY also resets catalogue_w_id_seq (owned by catalogue_services.w_id): tests start at W071.
CATALOGUE_TABLES = (
    "catalogue_categories, catalogue_specialisations, catalogue_services, qualifications, "
    "service_qualifications, specialisation_qualifications, catalogue_sync_imports, "
    "master_specialisations, master_competencies, master_qualifications, attachments"
)


def reseed_defaults(conn: Any) -> None:
    """TRUNCATE users CASCADE also empties the seeded settings tables (they reference users); restore them."""
    import json

    from app.services.settings import DEFAULTS

    conn.execute(text("TRUNCATE commercial_terms, commission_settings, system_settings CASCADE"))
    notes = {
        "materials": {
            "lv": "Materiāli un palīgmateriāli tiek apmaksāti atsevišķi.",
            "en": "Materials and consumables are paid separately.",
            "ru": "Материалы и расходные материалы оплачиваются отдельно.",
        }
    }
    conn.execute(
        text(
            "INSERT INTO commercial_terms (id, hourly_rate_eur, minimum_order_eur, public_notes, "
            "effective_from) "
            "VALUES (gen_random_uuid(), 40.00, 40.00, CAST(:n AS jsonb), now() - interval '1 day')"
        ),
        {"n": json.dumps(notes)},
    )
    conn.execute(
        text(
            "INSERT INTO commission_settings (id, rate, default_limit_eur) VALUES "
            "(gen_random_uuid(), 0.25, 100)"
        )
    )
    for key, value in DEFAULTS.items():
        conn.execute(
            text("INSERT INTO system_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"),
            {"k": key, "v": json.dumps(value)},
        )


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    limiter.reset()
    storage = get_storage()
    for key, _ in list(storage.objects()):
        storage.delete(key)
    with engine.begin() as conn:
        # TRUNCATE bypasses the append-only row triggers, which is what test cleanup needs.
        conn.execute(
            text(
                "TRUNCATE users, auth_sessions, master_profiles, domain_events, audit_log, "
                f"{CATALOGUE_TABLES} RESTART IDENTITY CASCADE"
            )
        )
        reseed_defaults(conn)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


_phone_counter = iter(range(20000000, 29999999))


def register(client: TestClient, role: str = "client", email: str | None = None) -> dict[str, Any]:
    n = next(_phone_counter)
    resp = client.post(
        f"/api/v1/auth/register/{role}",
        json={
            "email": email or f"user{n}@example.com",
            "password": PASSWORD,
            "full_name": f"Test {role}",
            "phone": f"+371{n}",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client: TestClient) -> str:
    with SessionLocal() as db:
        db.add(
            User(
                role="admin",
                email="admin@example.com",
                phone="+37130000000",
                full_name="Admin",
                password_hash=hash_password(PASSWORD),
            )
        )
        db.commit()
    resp = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


_CATALOGUE_MODELS: dict[str, Any] = {
    "categories": CatalogueCategory,
    "specialisations": CatalogueSpecialisation,
    "services": CatalogueService,
    "qualifications": Qualification,
}


def catalogue_version(url: str) -> int:
    """Current version of the catalogue entity a mutation URL points at (1 for an unknown ID).

    Catalogue mutations require `expected_version` (step 4.5.3.1); tests that are not about concurrency send
    the current one, like the admin UI does with the entity it has just loaded.
    """
    found = re.search(
        r"/admin/catalogue/(categories|specialisations|services|qualifications)/([0-9a-f-]{36})", url
    )
    assert found, url
    model = _CATALOGUE_MODELS[found.group(1)]
    with SessionLocal() as db:
        version = db.scalar(select(model.version).where(model.id == uuid.UUID(found.group(2))))
    return int(version) if version is not None else 1


def versioned(url: str, body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "expected_version": catalogue_version(url)}
