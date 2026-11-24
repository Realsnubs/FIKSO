"""Operational commands.

    python -m app.cli create-admin --email ... --name ... --phone ...
    python -m app.cli seed-catalogue      # production or isolated local/test DB only (R-CAT-16)
    python -m app.cli generate-signing-key --key-id prod-2026-11   # Ed25519 pair for catalogue packages

The password is read from FIKSO_ADMIN_PASSWORD or prompted, so it never appears in shell history.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.signing import generate_keypair
from app.integrations.storage import get_storage
from app.models import User
from app.schemas.auth import RegisterIn
from app.services.catalogue_seed import SeedError, seed_catalogue
from app.services.events import record_audit, record_event
from app.services.uploads import cleanup_orphans


def create_admin(email: str, name: str, phone: str) -> None:
    password = os.environ.get("FIKSO_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    data = RegisterIn(email=email, password=password, full_name=name, phone=phone)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(func.lower(User.email) == data.email.lower())):
            sys.exit("A user with this e-mail already exists.")
        user = User(
            role="admin",
            email=data.email.lower(),
            phone=data.phone,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
        )
        db.add(user)
        db.flush()
        record_audit(db, "user.admin_created", "user", user.id, "system", None, after={"role": "admin"})
        record_event(db, "user.registered", "user", user.id, "system", None, {"role": "admin"})
        db.commit()
    print("Admin created.")


def seed() -> None:
    with SessionLocal() as db:
        try:
            result = seed_catalogue(db)
        except SeedError as exc:
            sys.exit(f"Seed aborted, nothing written: {exc}")
    print(
        f"Catalogue seed: {result.categories} categories, {result.specialisations} specialisations, "
        f"{result.services} services created (existing rows left unchanged)."
    )


def generate_signing_key(key_id: str) -> None:
    # Printed once for the operator to put into the secret store; nothing is written to disk or logged.
    private, public = generate_keypair()
    print("Production secret store (never on staging):")
    print(f"  CATALOGUE_SIGNING_KEY_ID={key_id}")
    print(f"  CATALOGUE_SIGNING_PRIVATE_KEY={private}")
    print("Staging (public, add to the trusted map):")
    print(f'  CATALOGUE_TRUSTED_PUBLIC_KEYS={{"{key_id}": "{public}"}}')


def cleanup_orphan_files() -> None:
    with SessionLocal() as db:
        removed = cleanup_orphans(db, get_storage())
    # Only a count: storage keys are not secret, but there is nothing useful to log per file.
    print(f"Removed {removed} orphan file(s).")


def migrate_storage() -> None:
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.integrations.storage import LocalStorage, get_public_storage, get_storage
    from app.services.storage_migration import migrate

    settings = get_settings()
    if settings.storage_backend != "s3":
        raise SystemExit("Set STORAGE_BACKEND=s3 and the S3_* variables first.")
    with SessionLocal() as db:
        for label, source, target, private in (
            ("private", LocalStorage(settings.storage_local_dir), get_storage(), True),
            ("public", LocalStorage(settings.storage_public_dir), get_public_storage(), False),
        ):
            report = migrate(db, source, target, private=private)
            print(  # noqa: T201
                f"{label}: copied {report.copied}, already present {report.skipped_existing}, "
                f"mismatched {len(report.mismatched)}"
            )
            if report.mismatched:
                count = len(report.mismatched)
                raise SystemExit(f"{label}: content mismatch for {count} file(s); nothing deleted.")


def check_config() -> None:
    """Validates the settings and prints the readiness checks; exit code 1 when not ready."""
    import json

    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/api/v1/health/ready")
    print(json.dumps(response.json(), indent=2))  # noqa: T201
    if response.status_code != 200:
        raise SystemExit(1)


def worker_health(max_age_minutes: float) -> None:
    """Container healthcheck of the worker (it serves no HTTP): healthy while a pass finished recently."""
    from datetime import UTC, datetime, timedelta

    from app.models import JobRun

    with SessionLocal() as db:
        last = db.scalar(select(func.max(JobRun.finished_at)))
    if last is None or last < datetime.now(UTC) - timedelta(minutes=max_age_minutes):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create an admin account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    admin.add_argument("--phone", required=True)
    sub.add_parser("seed-catalogue", help="Insert the approved initial catalogue (docs/CATALOGUE_SEED.md)")
    keygen = sub.add_parser(
        "generate-signing-key", help="Generate an Ed25519 key pair for catalogue packages"
    )
    keygen.add_argument("--key-id", required=True)
    sub.add_parser(
        "cleanup-orphan-files", help="Delete stored files without a DB record that are older than 24 h"
    )
    sub.add_parser(
        "migrate-storage",
        help="Copy local private/public files to the configured S3 buckets (STORAGE_BACKEND=s3); idempotent",
    )
    sub.add_parser("check-config", help="Validate the configuration and print the readiness checks")
    jobs = sub.add_parser(
        "run-jobs", help="Run the background worker (offer/proposal expiry, rounds, outbox)"
    )
    jobs.add_argument("--interval", type=float, default=30.0, help="Seconds between passes (default 30)")
    jobs.add_argument("--once", action="store_true", help="Run one pass and exit")
    health = sub.add_parser("worker-health", help="Exit 1 unless a worker pass ran recently")
    health.add_argument("--max-age-minutes", type=float, default=5.0)
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.email, args.name, args.phone)
    elif args.command == "seed-catalogue":
        seed()
    elif args.command == "generate-signing-key":
        generate_signing_key(args.key_id)
    elif args.command == "cleanup-orphan-files":
        cleanup_orphan_files()
    elif args.command == "migrate-storage":
        migrate_storage()
    elif args.command == "check-config":
        check_config()
    elif args.command == "worker-health":
        worker_health(args.max_age_minutes)
    elif args.command == "run-jobs":
        from app.core.config import get_settings
        from app.core.logging import configure_logging
        from app.worker import run_forever, run_once

        configure_logging(get_settings().log_level)
        if args.once:
            print(run_once())  # noqa: T201
        else:
            run_forever(args.interval)


if __name__ == "__main__":
    main()
