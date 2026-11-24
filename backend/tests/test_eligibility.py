"""R-MST-11 eligibility and R-MST-12 reasons (Phase 2 step 4.2).

Every condition is tested alone and in every combination: one master per combination, then the SQL rule, the
reason explainer and an independent expectation written here must all agree.
"""

import itertools
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.core.business_time import business_today
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models import (
    CatalogueService,
    CatalogueSpecialisation,
    MasterCompetency,
    MasterProfile,
    MasterQualification,
    MasterSpecialisation,
    Qualification,
    User,
)
from app.models.catalogue import QUALIFICATION_STATUSES, service_qualifications, specialisation_qualifications
from app.services import eligibility as el
from app.services.catalogue_seed import seed_catalogue, seed_id

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

SPEC = seed_id("cm-s01")
SERVICE = seed_id("cm-s01-1")  # W071, no requirements
OTHER_SERVICE = seed_id("cm-s01-2")  # W072, same specialisation
OTHER_SPEC = seed_id("cm-s02")
OTHER_SPEC_SERVICE = seed_id("cm-s02-1")

DECIDED = ("approved", "verified", "rejected", "revoked")


@dataclass
class World:
    db: Session
    admin_id: uuid.UUID
    counter: Iterator[int]

    def master(self, *, user: str = "active", profile: str = "approved") -> uuid.UUID:
        n = next(self.counter)
        user_row = User(
            role="master",
            email=f"m{n}@example.lv",
            password_hash="x",
            full_name=f"Meistars {n}",
            status="blocked" if user == "blocked" else "active",
            deleted_at=NOW if user == "deleted" else None,
        )
        self.db.add(user_row)
        self.db.flush()
        decided = {"decided_by": self.admin_id, "decided_at": NOW} if profile != "pending_approval" else {}
        profile_row = MasterProfile(user_id=user_row.id, approval_status=profile, **decided)
        self.db.add(profile_row)
        self.db.flush()
        return profile_row.id

    def _decision(self, status: str) -> dict[str, Any]:
        return {"decided_by": self.admin_id, "decided_at": NOW} if status in DECIDED else {}

    def specialisation(self, master_id: uuid.UUID, status: str | None, spec_id: uuid.UUID = SPEC) -> None:
        if status:
            self.db.add(
                MasterSpecialisation(
                    master_id=master_id, specialisation_id=spec_id, status=status, **self._decision(status)
                )
            )

    def competency(self, master_id: uuid.UUID, status: str | None, service_id: uuid.UUID = SERVICE) -> None:
        if status:
            self.db.add(
                MasterCompetency(
                    master_id=master_id, service_id=service_id, status=status, **self._decision(status)
                )
            )

    def submission(
        self,
        master_id: uuid.UUID,
        qualification_id: uuid.UUID,
        status: str,
        valid_until: date | None = None,
        at: datetime = NOW,
    ) -> MasterQualification:
        row = MasterQualification(
            master_id=master_id,
            qualification_id=qualification_id,
            status=status,
            valid_until=valid_until,
            submitted_at=at,
            **self._decision(status),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def full(self, service_id: uuid.UUID = SERVICE, spec_id: uuid.UUID = SPEC) -> uuid.UUID:
        """A master who passes every non-qualification condition for the service."""
        master_id = self.master()
        self.specialisation(master_id, "approved", spec_id)
        self.competency(master_id, "verified", service_id)
        return master_id

    def qualification(self, name: str, status: str = "active") -> uuid.UUID:
        row = Qualification(name=name, status=status)
        self.db.add(row)
        self.db.flush()
        return row.id

    def require(
        self, qualification_id: uuid.UUID, *, service: uuid.UUID | None = None, spec: uuid.UUID | None = None
    ) -> None:
        if service:
            self.db.execute(
                insert(service_qualifications).values(service_id=service, qualification_id=qualification_id)
            )
        if spec:
            self.db.execute(
                insert(specialisation_qualifications).values(
                    specialisation_id=spec, qualification_id=qualification_id
                )
            )


@pytest.fixture
def world() -> Iterator[World]:
    with SessionLocal() as db:
        seed_catalogue(db)
        admin = User(role="admin", email="admin@example.lv", password_hash="x", full_name="Admin")
        db.add(admin)
        db.flush()
        yield World(db, admin.id, itertools.count())


def _codes(result: el.Eligibility) -> list[str]:
    return [r.code for r in result.reasons]


def _check(
    world: World, service_id: uuid.UUID, expected: dict[uuid.UUID, list[str]], today: date = TODAY
) -> None:
    """The explainer gives exactly the expected reasons; the SQL rule selects exactly the expected masters."""
    world.db.flush()
    explained = el.explain(world.db, service_id, list(expected), today)
    assert {m: _codes(r) for m, r in explained.items()} == expected
    eligible = {m for m, codes in expected.items() if not codes}
    assert set(el.eligible_master_ids(world.db, service_id, today)) == eligible
    for master_id, codes in expected.items():
        assert world.db.scalar(select(el.eligible(master_id, service_id, today))) is (not codes)


def test_every_combination_of_account_specialisation_and_competency(world: World) -> None:
    users = ("active", "blocked", "deleted")
    profiles = ("pending_approval", "approved", "rejected")
    statuses = (None, "requested", "approved", "rejected", "revoked", "withdrawn")
    competencies = (None, "declared", "verified", "rejected", "revoked", "withdrawn")
    expected = {}
    for user, profile, spec, comp in itertools.product(users, profiles, statuses, competencies):
        master_id = world.master(user=user, profile=profile)
        world.specialisation(master_id, spec)
        world.competency(master_id, comp)
        codes = []
        if user != "active":
            codes.append(el.USER_NOT_ACTIVE)
        if profile != "approved":
            codes.append(el.PROFILE_NOT_APPROVED)
        if spec != "approved":
            codes.append(el.SPECIALISATION_NOT_APPROVED)
        if comp != "verified":
            codes.append(el.COMPETENCY_NOT_VERIFIED)
        expected[master_id] = codes
    assert len(expected) == 324
    _check(world, SERVICE, expected)
    assert len(el.eligible_master_ids(world.db, SERVICE, TODAY)) == 1


# Submission history as (status, valid_until offset in days or None) -> expected reason for an active type.
HISTORIES: dict[str, tuple[list[tuple[str, int | None]], str | None]] = {
    "none": ([], el.QUALIFICATION_MISSING),
    "submitted": ([("submitted", None)], el.QUALIFICATION_MISSING),
    "verified_open_ended": ([("verified", None)], None),
    "verified_future": ([("verified", 30)], None),
    "verified_until_today": ([("verified", 0)], None),
    "verified_until_yesterday": ([("verified", -1)], el.QUALIFICATION_EXPIRED),
    "verified_long_expired": ([("verified", -400)], el.QUALIFICATION_EXPIRED),
    "rejected": ([("rejected", None)], el.QUALIFICATION_MISSING),
    "revoked": ([("revoked", 30)], el.QUALIFICATION_REVOKED),
    "withdrawn": ([("withdrawn", 30)], el.QUALIFICATION_MISSING),
    "revoked_then_resubmitted": ([("revoked", 30), ("submitted", 60)], el.QUALIFICATION_MISSING),
    "rejected_then_verified": ([("rejected", None), ("verified", 60)], None),
    "verified_after_revocation": ([("revoked", None), ("verified", None)], None),
    "withdrawn_then_revoked": ([("withdrawn", None), ("revoked", None)], el.QUALIFICATION_REVOKED),
}


@pytest.mark.parametrize("via", ["service", "specialisation", "both"])
@pytest.mark.parametrize("type_status", QUALIFICATION_STATUSES)
def test_every_qualification_state_and_requirement_source(world: World, via: str, type_status: str) -> None:
    qualification_id = world.qualification("Sertifikāts", type_status)
    world.require(
        qualification_id,
        service=SERVICE if via in ("service", "both") else None,
        spec=SPEC if via in ("specialisation", "both") else None,
    )
    expected = {}
    for history, held_reason in HISTORIES.values():
        master_id = world.full()
        for i, (status, offset) in enumerate(history):
            until = None if offset is None else TODAY + timedelta(days=offset)
            world.submission(master_id, qualification_id, status, until, NOW + timedelta(minutes=i))
        codes = [] if type_status == "active" else [el.QUALIFICATION_TYPE_NOT_ACTIVE]
        expected[master_id] = codes + ([held_reason] if held_reason else [])
    # A requirement listed on both the service and its specialisation is one requirement, reported once.
    _check(world, SERVICE, expected)


def test_reason_details_name_the_failing_item(world: World) -> None:
    qualification_id = world.qualification("Elektrodrošība", "draft")
    world.require(qualification_id, service=SERVICE)
    master_id = world.master(user="blocked", profile="pending_approval")
    world.specialisation(master_id, "revoked")
    world.competency(master_id, "declared")
    world.submission(master_id, qualification_id, "verified", TODAY - timedelta(days=1))
    world.db.flush()
    result = el.explain(world.db, SERVICE, [master_id], TODAY)[master_id]
    q = {"qualification_id": str(qualification_id), "name": "Elektrodrošība"}
    assert result.reasons == (
        el.Reason(el.USER_NOT_ACTIVE, {"status": "blocked", "deleted": False}),
        el.Reason(el.PROFILE_NOT_APPROVED, {"approval_status": "pending_approval"}),
        el.Reason(el.SPECIALISATION_NOT_APPROVED, {"specialisation_id": str(SPEC), "status": "revoked"}),
        el.Reason(el.COMPETENCY_NOT_VERIFIED, {"service_id": str(SERVICE), "status": "declared"}),
        el.Reason(el.QUALIFICATION_TYPE_NOT_ACTIVE, q | {"type_status": "draft"}),
        el.Reason(el.QUALIFICATION_EXPIRED, q | {"valid_until": "2026-11-01"}),
    )
    assert not result.eligible
    missing = world.master()
    world.db.flush()
    assert el.explain(world.db, SERVICE, [missing], TODAY)[missing].reasons[:2] == (
        el.Reason(el.SPECIALISATION_NOT_APPROVED, {"specialisation_id": str(SPEC), "status": None}),
        el.Reason(el.COMPETENCY_NOT_VERIFIED, {"service_id": str(SERVICE), "status": None}),
    )


def test_every_required_qualification_must_hold(world: World) -> None:
    gas = world.qualification("A")
    water = world.qualification("B")
    world.require(gas, service=SERVICE)
    world.require(water, spec=SPEC)
    both, only_gas, one_expired, none = world.full(), world.full(), world.full(), world.full()
    for master_id in (both, one_expired):
        world.submission(master_id, gas, "verified")
    world.submission(both, water, "verified", TODAY)
    world.submission(only_gas, gas, "verified", TODAY + timedelta(days=1))
    world.submission(one_expired, water, "verified", TODAY - timedelta(days=1))
    _check(
        world,
        SERVICE,
        {
            both: [],
            only_gas: [el.QUALIFICATION_MISSING],
            one_expired: [el.QUALIFICATION_EXPIRED],
            none: [el.QUALIFICATION_MISSING, el.QUALIFICATION_MISSING],
        },
    )
    reasons = el.explain(world.db, SERVICE, [none], TODAY)[none].reasons
    assert [r.details["name"] for r in reasons] == ["A", "B"]


def test_valid_until_is_inclusive_and_expires_the_next_day(world: World) -> None:
    qualification_id = world.qualification("Sertifikāts")
    world.require(qualification_id, service=SERVICE)
    master_id = world.full()
    submission = world.submission(master_id, qualification_id, "verified", TODAY)
    _check(world, SERVICE, {master_id: []}, today=TODAY)
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_EXPIRED]}, today=TODAY + timedelta(days=1))
    # Expiry changes no stored state: the submission and the competency keep their statuses.
    world.db.refresh(submission)
    assert submission.status == "verified"
    assert (
        world.db.scalar(select(MasterCompetency.status).where(MasterCompetency.master_id == master_id))
        == "verified"
    )


def test_business_today_is_the_riga_calendar_date(world: World) -> None:
    db = world.db
    # Winter (UTC+2) and summer (UTC+3) boundaries of the Riga day.
    assert business_today(db, datetime(2026, 11, 2, 21, 59, 59, tzinfo=UTC)) == date(2026, 11, 2)
    assert business_today(db, datetime(2026, 11, 2, 22, 0, 0, tzinfo=UTC)) == date(2026, 11, 3)
    assert business_today(db, datetime(2026, 7, 1, 20, 59, 59, tzinfo=UTC)) == date(2026, 7, 1)
    assert business_today(db, datetime(2026, 7, 1, 21, 0, 0, tzinfo=UTC)) == date(2026, 7, 2)
    # The rule defaults to the same business date the helper reports.
    today = business_today(db)
    qualification_id = world.qualification("Sertifikāts")
    world.require(qualification_id, service=SERVICE)
    valid, expired = world.full(), world.full()
    world.submission(valid, qualification_id, "verified", today)
    world.submission(expired, qualification_id, "verified", today - timedelta(days=1))
    db.flush()
    assert el.eligible_master_ids(db, SERVICE) == [valid]
    explained = el.explain(db, SERVICE, [valid, expired])
    assert explained[valid].eligible and _codes(explained[expired]) == [el.QUALIFICATION_EXPIRED]


def test_revocation_excludes_at_once_without_rewriting_competency(world: World) -> None:
    qualification_id = world.qualification("Sertifikāts")
    world.require(qualification_id, service=SERVICE)
    master_id = world.full()
    submission = world.submission(master_id, qualification_id, "verified")
    _check(world, SERVICE, {master_id: []})

    submission.status = "revoked"
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_REVOKED]})
    submission.status = "verified"
    world.db.execute(update(MasterSpecialisation).values(status="revoked"))
    _check(world, SERVICE, {master_id: [el.SPECIALISATION_NOT_APPROVED]})
    world.db.execute(update(MasterSpecialisation).values(status="approved"))
    world.db.execute(update(Qualification).values(status="archived"))
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_TYPE_NOT_ACTIVE]})
    world.db.execute(update(User).where(User.role == "master").values(status="blocked"))
    _check(world, SERVICE, {master_id: [el.USER_NOT_ACTIVE, el.QUALIFICATION_TYPE_NOT_ACTIVE]})
    assert world.db.scalar(select(MasterCompetency.status)) == "verified"


def test_nothing_of_another_master_service_or_specialisation_counts(world: World) -> None:
    qualification_id = world.qualification("Sertifikāts")
    world.require(qualification_id, service=SERVICE)
    holder = world.full()
    world.submission(holder, qualification_id, "verified")
    # Approved in another specialisation, verified for another service, qualification held only by `holder`.
    wrong_spec = world.master()
    world.specialisation(wrong_spec, "approved", OTHER_SPEC)
    world.competency(wrong_spec, "verified")
    wrong_service = world.master()
    world.specialisation(wrong_service, "approved")
    world.competency(wrong_service, "verified", OTHER_SERVICE)
    world.submission(wrong_service, qualification_id, "verified")
    no_qualification = world.full()
    _check(
        world,
        SERVICE,
        {
            holder: [],
            wrong_spec: [el.SPECIALISATION_NOT_APPROVED, el.QUALIFICATION_MISSING],
            wrong_service: [el.COMPETENCY_NOT_VERIFIED],
            no_qualification: [el.QUALIFICATION_MISSING],
        },
    )
    # The requirement is on W071 only; the same master is unaffected by it elsewhere.
    world.competency(no_qualification, "verified", OTHER_SERVICE)
    _check(world, OTHER_SERVICE, {no_qualification: [], wrong_service: []})


def test_specialisation_requirement_applies_to_its_services_only(world: World) -> None:
    qualification_id = world.qualification("Sertifikāts")
    world.require(qualification_id, spec=OTHER_SPEC)
    master_id = world.full()
    world.specialisation(master_id, "approved", OTHER_SPEC)
    world.competency(master_id, "verified", OTHER_SPEC_SERVICE)
    _check(world, SERVICE, {master_id: []})
    _check(world, OTHER_SPEC_SERVICE, {master_id: [el.QUALIFICATION_MISSING]})


def test_rule_composes_into_other_queries(world: World) -> None:
    """Catalogue counts (step 4.5) and matching embed the same condition in their own queries."""
    world.full()
    world.full()
    other = world.full(OTHER_SERVICE)
    world.competency(other, "declared")  # declared never counts
    world.db.flush()
    counts = dict(
        world.db.execute(
            select(CatalogueService.w_id, func.count(MasterProfile.id))
            .join(MasterProfile, el.eligible(MasterProfile.id, CatalogueService.id, TODAY))
            .group_by(CatalogueService.w_id)
        ).all()
    )
    assert counts == {"W071": 2, "W072": 1}


def test_explain_rejects_unknown_service_and_skips_unknown_masters(world: World) -> None:
    with pytest.raises(AppError) as exc:
        el.explain(world.db, uuid.uuid4(), [], TODAY)
    assert exc.value.code == "SERVICE_NOT_FOUND"
    assert el.explain(world.db, SERVICE, [uuid.uuid4()], TODAY) == {}


def test_business_today_refuses_naive_datetimes(world: World) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        business_today(world.db, datetime(2026, 11, 2, 12, 0))


def _regulate(world: World, *, service: uuid.UUID | None = None, spec: uuid.UUID | None = None) -> None:
    if service:
        world.db.execute(
            update(CatalogueService).where(CatalogueService.id == service).values(qualification_required=True)
        )
    if spec:
        world.db.execute(
            update(CatalogueSpecialisation)
            .where(CatalogueSpecialisation.id == spec)
            .values(qualification_required=True)
        )


def _eligible_counts(world: World) -> dict[str, int]:
    """The catalogue's `eligible_masters` shape (step 4.5): the shared condition per service."""
    world.db.flush()
    return dict(
        world.db.execute(
            select(CatalogueService.w_id, func.count(MasterProfile.id))
            .join(MasterProfile, el.eligible(MasterProfile.id, CatalogueService.id, TODAY))
            .group_by(CatalogueService.w_id)
        ).all()
    )


@pytest.mark.parametrize("flag_on", ["service", "specialisation"])
def test_regulated_service_without_requirements_admits_nobody(world: World, flag_on: str) -> None:
    _regulate(
        world,
        service=SERVICE if flag_on == "service" else None,
        spec=SPEC if flag_on == "specialisation" else None,
    )
    full = world.full()
    world.competency(full, "verified", OTHER_SERVICE)
    declared = world.master()
    world.specialisation(declared, "approved")
    world.competency(declared, "declared")
    not_configured = [el.QUALIFICATION_NOT_CONFIGURED]
    _check(world, SERVICE, {full: not_configured, declared: [el.COMPETENCY_NOT_VERIFIED, *not_configured]})
    reason = el.explain(world.db, SERVICE, [full], TODAY)[full].reasons[0]
    assert reason == el.Reason(el.QUALIFICATION_NOT_CONFIGURED, {"service_id": str(SERVICE)})
    # A specialisation flag regulates all its services; a service flag only that service.
    other_expected = not_configured if flag_on == "specialisation" else []
    _check(
        world, OTHER_SERVICE, {full: other_expected, declared: [el.COMPETENCY_NOT_VERIFIED, *other_expected]}
    )
    counts = _eligible_counts(world)
    assert "W071" not in counts
    assert counts.get("W072", 0) == (0 if flag_on == "specialisation" else 1)


@pytest.mark.parametrize("requirement_on", ["service", "specialisation"])
def test_configuring_requirements_then_verifying_admits_the_master(world: World, requirement_on: str) -> None:
    _regulate(world, service=SERVICE)
    master_id = world.full()
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_NOT_CONFIGURED]})
    qualification_id = world.qualification("Sertifikāts", "draft")
    world.require(
        qualification_id,
        service=SERVICE if requirement_on == "service" else None,
        spec=SPEC if requirement_on == "specialisation" else None,
    )
    # Configured but not yet an active type: that reason replaces "not configured".
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_TYPE_NOT_ACTIVE, el.QUALIFICATION_MISSING]})
    world.db.execute(update(Qualification).values(status="active"))
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_MISSING]})
    world.submission(master_id, qualification_id, "verified", TODAY)
    _check(world, SERVICE, {master_id: []})
    assert _eligible_counts(world)["W071"] == 1


def test_renewal_admits_only_once_the_new_submission_is_verified(world: World) -> None:
    qualification_id = world.qualification("Sertifikāts")
    _regulate(world, service=SERVICE)
    world.require(qualification_id, service=SERVICE)
    master_id = world.full()
    old = world.submission(master_id, qualification_id, "verified", TODAY - timedelta(days=10))
    renewal = world.submission(master_id, qualification_id, "submitted", TODAY + timedelta(days=365))
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_EXPIRED]})
    reason = el.explain(world.db, SERVICE, [master_id], TODAY)[master_id].reasons[0]
    assert reason.details["valid_until"] == (TODAY - timedelta(days=10)).isoformat()
    renewal.status, renewal.decided_by, renewal.decided_at = "verified", world.admin_id, NOW
    _check(world, SERVICE, {master_id: []})
    world.db.refresh(old)
    assert (old.status, old.valid_until) == ("verified", TODAY - timedelta(days=10))
    # Both verified rows expired: the reason names the later end date.
    _check(world, SERVICE, {master_id: [el.QUALIFICATION_EXPIRED]}, today=TODAY + timedelta(days=366))
    reason = el.explain(world.db, SERVICE, [master_id], TODAY + timedelta(days=366))[master_id].reasons[0]
    assert reason.details["valid_until"] == (TODAY + timedelta(days=365)).isoformat()
