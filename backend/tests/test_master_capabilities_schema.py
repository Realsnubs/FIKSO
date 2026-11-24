"""DB-level guarantees of migration 0004_master_capabilities (Phase 2 step 4.1)."""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    Attachment,
    CatalogueService,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
)
from app.services.catalogue_seed import seed_catalogue, seed_id
from tests.conftest import register


@dataclass
class Fixture:
    master_id: uuid.UUID
    user_id: uuid.UUID
    spec_id: uuid.UUID
    service_id: uuid.UUID
    qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient) -> Iterator[Fixture]:
    user_id = uuid.UUID(register(client, "master")["user"]["id"])
    with SessionLocal() as db:
        seed_catalogue(db)
        qualification = Qualification(name="Sertifikāts", status="active")
        db.add(qualification)
        db.commit()
        master = db.scalar(select(MasterProfile).where(MasterProfile.user_id == user_id))
        assert master is not None
        yield Fixture(master.id, user_id, seed_id("cm-s01"), seed_id("cm-s01-1"), qualification.id)


def _fails(db: Session, statement: object, error: type[Exception] = DBAPIError) -> None:
    with pytest.raises(error):
        db.execute(statement)  # type: ignore[call-overload]
        db.flush()
    db.rollback()


def test_decisions_must_name_decider_and_time(fx: Fixture) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for row in (
            MasterSpecialisation(master_id=fx.master_id, specialisation_id=fx.spec_id, status="approved"),
            MasterCompetency(master_id=fx.master_id, service_id=fx.service_id, status="verified"),
            MasterQualification(
                master_id=fx.master_id, qualification_id=fx.qualification_id, status="verified"
            ),
        ):
            db.add(row)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
        db.add(
            MasterSpecialisation(
                master_id=fx.master_id,
                specialisation_id=fx.spec_id,
                status="approved",
                decided_by=fx.user_id,
                decided_at=now,
            )
        )
        db.add(
            MasterCompetency(master_id=fx.master_id, service_id=fx.service_id)
        )  # declared needs no decider
        db.commit()


def test_unknown_statuses_are_rejected(fx: Fixture) -> None:
    with SessionLocal() as db:
        db.add(MasterCompetency(master_id=fx.master_id, service_id=fx.service_id, status="approved"))
        with pytest.raises(IntegrityError):
            db.flush()


def test_one_pending_submission_per_qualification(fx: Fixture) -> None:
    with SessionLocal() as db:
        first = MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id)
        db.add(first)
        db.commit()
        db.add(MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        first.status = "withdrawn"
        db.commit()
        # History stays; a new submission is a new row.
        db.add(
            MasterQualification(
                master_id=fx.master_id, qualification_id=fx.qualification_id, valid_until=date(2027, 12, 31)
            )
        )
        db.commit()
        rows = db.scalars(select(MasterQualification).where(MasterQualification.master_id == fx.master_id))
        assert sorted(r.status for r in rows) == ["submitted", "withdrawn"]


def test_renewal_may_sit_next_to_a_verified_row(fx: Fixture) -> None:
    """0005: a verified (expired) row and one pending renewal coexist; a second pending one does not."""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            MasterQualification(
                master_id=fx.master_id,
                qualification_id=fx.qualification_id,
                status="verified",
                valid_until=date(2026, 1, 31),
                decided_by=fx.user_id,
                decided_at=now,
            )
        )
        db.add(MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id))
        db.commit()
        db.add(MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id))
        with pytest.raises(IntegrityError):
            db.flush()


def test_history_rows_cannot_be_deleted_or_rekeyed(fx: Fixture) -> None:
    with SessionLocal() as db:
        db.add(MasterSpecialisation(master_id=fx.master_id, specialisation_id=fx.spec_id))
        db.add(MasterCompetency(master_id=fx.master_id, service_id=fx.service_id))
        submission = MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id)
        db.add(submission)
        db.commit()
        other_service = db.scalar(select(CatalogueService.id).where(CatalogueService.w_id == "W072"))
        for table in ("master_specialisations", "master_competencies", "master_qualifications"):
            _fails(db, text(f"DELETE FROM {table}"))  # noqa: S608 - table names are literals above
        _fails(db, update(MasterCompetency).values(service_id=other_service))
        _fails(db, update(MasterSpecialisation).values(specialisation_id=seed_id("cm-s02")))
        _fails(db, update(MasterQualification).values(master_id=uuid.uuid4()))
        # Status changes are normal updates.
        db.execute(update(MasterCompetency).values(status="withdrawn"))
        db.commit()


def test_attachments_are_immutable_and_bound(fx: Fixture) -> None:
    with SessionLocal() as db:
        submission = MasterQualification(master_id=fx.master_id, qualification_id=fx.qualification_id)
        db.add(submission)
        db.flush()
        attachment = Attachment(
            owner_user_id=fx.user_id,
            entity_type="qualification",
            entity_id=submission.id,
            storage_key=uuid.uuid4().hex,
            mime_type="application/pdf",
            size_bytes=1234,
            sha256=hashlib.sha256(b"x").hexdigest(),
        )
        db.add(attachment)
        db.commit()
        _fails(db, update(Attachment).values(entity_id=uuid.uuid4()))
        _fails(db, update(Attachment).values(owner_user_id=uuid.uuid4()))
        _fails(db, text("DELETE FROM attachments"))
        duplicate_key = Attachment(
            owner_user_id=fx.user_id,
            entity_type="qualification",
            entity_id=submission.id,
            storage_key=attachment.storage_key,
            mime_type="image/png",
            size_bytes=1,
            sha256="0" * 64,
        )
        db.add(duplicate_key)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        for bad in ({"size_bytes": 0}, {"sha256": "short"}, {"entity_type": "other"}):
            values = {
                "owner_user_id": fx.user_id,
                "entity_type": "qualification",
                "entity_id": submission.id,
                "storage_key": uuid.uuid4().hex,
                "mime_type": "image/png",
                "size_bytes": 1,
                "sha256": "0" * 64,
            } | bad
            db.add(Attachment(**values))
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


def test_catalogue_entries_in_use_stay_referenced(fx: Fixture) -> None:
    with SessionLocal() as db:
        db.add(MasterCompetency(master_id=fx.master_id, service_id=fx.service_id))
        db.commit()
        # Catalogue rows were already undeletable; the master's history also pins them via RESTRICT FKs.
        _fails(db, text("DELETE FROM catalogue_services WHERE w_id = 'W071'"))
        _fails(db, text("DELETE FROM master_profiles"))
