"""Initial catalogue seed (R-CAT-11, docs/CATALOGUE_SEED.md).

Insert-missing only: rows that already exist are never updated, so admin edits survive re-runs.
UUIDs are derived from `source_ref`, so every environment that seeds gets identical UUIDs and W-IDs.
Runs in production (issuer) or isolated local/test databases; staging gets the catalogue by import (R-CAT-16).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CatalogueCategory, CatalogueService, CatalogueSpecialisation
from app.seed.catalogue_cm_v1 import CATEGORIES
from app.services.catalogue import advance_w_id_sequence
from app.services.events import record_audit, record_event

SOURCE = "seed_cm_v1"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://fiksoapp.eu/catalogue/seed_cm_v1")


class SeedError(Exception):
    pass


@dataclass
class SeedResult:
    categories: int = 0
    specialisations: int = 0
    services: int = 0

    @property
    def total(self) -> int:
        return self.categories + self.specialisations + self.services


def seed_id(source_ref: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, source_ref)


def _services() -> list[dict[str, Any]]:
    return [svc for cat in CATEGORIES for spec in cat["specialisations"] for svc in spec["services"]]


def _check_conflicts(db: Session) -> None:
    """Abort before writing anything if a seed W-ID or UUID is already used differently."""
    for svc in _services():
        expected_id = seed_id(svc["ref"])
        holder = db.scalar(select(CatalogueService).where(CatalogueService.w_id == svc["w_id"]))
        if holder is not None and holder.id != expected_id:
            raise SeedError(f"{svc['w_id']} is already used by another service ({holder.id}).")
        existing = db.get(CatalogueService, expected_id)
        if existing is not None and existing.w_id != svc["w_id"]:
            raise SeedError(f"Seed service {svc['ref']} exists with W-ID {existing.w_id}.")


def seed_catalogue(db: Session) -> SeedResult:
    if get_settings().catalogue_role == "receiver":
        raise SeedError("Staging does not seed the catalogue; import a production export instead.")
    _check_conflicts(db)
    result = SeedResult()
    for c_pos, cat in enumerate(CATEGORIES):
        category = db.get(CatalogueCategory, seed_id(cat["ref"]))
        if category is None:
            category = CatalogueCategory(
                id=seed_id(cat["ref"]),
                name=cat["name"],
                status=cat["status"],
                sort_order=c_pos,
                source=SOURCE,
                source_ref=cat["ref"],
            )
            db.add(category)
            result.categories += 1
        for s_pos, spec_data in enumerate(cat["specialisations"]):
            spec = db.get(CatalogueSpecialisation, seed_id(spec_data["ref"]))
            if spec is None:
                spec = CatalogueSpecialisation(
                    id=seed_id(spec_data["ref"]),
                    category_id=category.id,
                    name=spec_data["name"],
                    description=spec_data["description"],
                    status=spec_data["status"],
                    sort_order=s_pos,
                    source=SOURCE,
                    source_ref=spec_data["ref"],
                )
                db.add(spec)
                result.specialisations += 1
            for v_pos, svc in enumerate(spec_data["services"]):
                if db.get(CatalogueService, seed_id(svc["ref"])) is None:
                    db.add(
                        CatalogueService(
                            id=seed_id(svc["ref"]),
                            specialisation_id=spec.id,
                            w_id=svc["w_id"],
                            name=svc["name"],
                            status="draft",
                            sort_order=v_pos,
                            qualification_required=svc["qualification_required"],
                            review_note=svc["review_note"],
                            source=SOURCE,
                            source_ref=svc["ref"],
                        )
                    )
                    result.services += 1
        db.flush()
    # Next admin-created W-ID becomes W143 (Q-20); GREATEST inside keeps the sequence monotonic.
    advance_w_id_sequence(db, [svc["w_id"] for svc in _services()])
    if result.total:
        counts = {
            "categories": result.categories,
            "specialisations": result.specialisations,
            "services": result.services,
        }
        record_audit(
            db, "catalogue.seeded", "catalogue_seed", None, "system", None, after=counts | {"source": SOURCE}
        )
        record_event(db, "catalogue.seeded", "catalogue_seed", NAMESPACE, "system", None, counts)
    db.commit()
    return result
