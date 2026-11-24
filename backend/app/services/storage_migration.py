"""Copy files from the local directories to the configured S3 buckets (idempotent, verifying content).

Private files go only to the private bucket and public variants only to the public bucket. Each private
file with an `attachments` row is checked against its stored SHA-256 before upload, and every uploaded
object is read back and compared. Local files are never deleted by this command.
"""

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.storage import Storage
from app.models import Attachment


@dataclass
class MigrationReport:
    copied: int = 0
    skipped_existing: int = 0
    mismatched: list[str] = field(default_factory=list)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def migrate(db: Session, source: Storage, target: Storage, *, private: bool) -> MigrationReport:
    report = MigrationReport()
    expected = {}
    if private:
        rows = db.execute(select(Attachment.storage_key, Attachment.sha256))
        expected = {key: digest for key, digest in rows}
    for key, _ in source.objects():
        with source.open(key) as handle:
            data = handle.read()
        if private and key in expected and _sha(data) != expected[key]:
            report.mismatched.append(key)  # corrupted locally: not copied, reported for a human
            continue
        if target.exists(key):  # type: ignore[attr-defined]
            report.skipped_existing += 1
            continue
        target.put(key, data)
        with target.open(key) as handle:
            if _sha(handle.read()) != _sha(data):
                report.mismatched.append(key)
                continue
        report.copied += 1
    return report
