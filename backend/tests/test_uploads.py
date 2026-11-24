"""Evidence file validation and storage (R-MST-15, Q-26; Phase 2 step 4.3)."""

import io
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import UploadFile

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.integrations.storage import LocalStorage, new_key
from app.models import Attachment, User
from app.services import uploads
from tests.files import HEIC, JPEG, PDF, PNG, WEBP


def _upload(data: bytes, name: str = "doc.pdf", content_type: str = "application/pdf") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers={"content-type": content_type})  # type: ignore[arg-type]


def _validate(*files: UploadFile) -> list[uploads.ValidFile]:
    return uploads.validate_files(list(files))


def _error(*files: UploadFile) -> AppError:
    with pytest.raises(AppError) as exc:
        _validate(*files)
    return exc.value


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PDF, "application/pdf"),
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (HEIC, "image/heic"),
    ],
)
def test_format_is_detected_from_content(data: bytes, mime: str) -> None:
    # Name and declared type are deliberately wrong: only the bytes count.
    [file] = _validate(_upload(data, "x.txt", "text/plain"))
    assert file.mime_type == mime and file.data == data and len(file.sha256) == 64


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00 windows executable",  # renamed .exe
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"<html><script>alert(1)</script></html>",
        b"GIF89a" + b"\x00" * 16,
        b"PK\x03\x04 zip or docx",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00",  # MP4, same container family as HEIC
        b"RIFF\x24\x00\x00\x00WAVEfmt ",  # RIFF but not WebP
        b" %PDF-1.7 leading byte",
    ],
)
def test_other_content_is_refused_even_with_an_allowed_name(data: bytes) -> None:
    error = _error(_upload(PDF), _upload(data, "scan.pdf", "application/pdf"))
    assert (error.code, error.status_code, error.details) == ("UNSUPPORTED_FILE_TYPE", 415, {"index": 1})


def test_size_and_count_limits() -> None:
    assert len(_validate(*[_upload(PDF) for _ in range(5)])) == 5
    assert _error(*[_upload(PDF) for _ in range(6)]).code == "TOO_MANY_FILES"
    exactly_max = PDF + b"0" * (uploads.MAX_FILE_BYTES - len(PDF))
    assert _validate(_upload(exactly_max))[0].data == exactly_max
    too_big = _error(_upload(exactly_max + b"0"))
    assert (too_big.code, too_big.status_code) == ("FILE_TOO_LARGE", 413)
    assert _error(_upload(b"")).code == "FILE_EMPTY"


def test_local_storage_accepts_only_its_own_random_keys(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    key = new_key()
    storage.put(key, b"data")
    with storage.open(key) as f:
        assert f.read() == b"data"
    assert (tmp_path / "files" / key).stat().st_mode & 0o777 == 0o600
    assert [k for k, _ in storage.objects()] == [key]
    for bad in ("../etc/passwd", "/etc/passwd", key + "/x", key.upper(), "", "a" * 31):
        with pytest.raises(ValueError):
            storage.open(bad)
        with pytest.raises(ValueError):
            storage.put(bad, b"x")
    storage.delete(key)
    assert list(storage.objects()) == []
    assert new_key() != new_key()


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.rolled_back = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def rollback(self) -> None:
        self.rolled_back = True


def test_written_files_are_removed_when_the_record_fails(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    db: Any = _FakeSession()
    files = _validate(_upload(PDF), _upload(PNG))
    with (
        pytest.raises(RuntimeError, match="commit failed"),
        uploads.store_attachments(
            db,
            storage,
            files,
            owner_user_id=uuid.uuid4(),
            entity_type="qualification",
            entity_id=uuid.uuid4(),
        ) as rows,
    ):
        assert len(rows) == 2 and len(list(storage.objects())) == 2
        raise RuntimeError("commit failed")
    assert list(storage.objects()) == [] and db.rolled_back


def test_orphan_cleanup_removes_only_old_files_without_a_record(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    now = datetime.now(UTC)
    ages = {
        "orphan_24h01": timedelta(hours=24, minutes=1),
        "orphan_23h59": timedelta(hours=23, minutes=59),
        "orphan_year": timedelta(days=365),
        "row_24h01": timedelta(hours=24, minutes=1),
        "row_year": timedelta(days=365),
    }
    keys = {name: new_key() for name in ages}
    for name, age in ages.items():
        storage.put(keys[name], b"x")
        stamp = (now - age).timestamp()
        os.utime(tmp_path / keys[name], (stamp, stamp))
    with SessionLocal() as db:
        user = User(role="master", email="o@example.lv", password_hash="x", full_name="O")
        db.add(user)
        db.flush()
        for name in ("row_24h01", "row_year"):
            db.add(
                Attachment(
                    owner_user_id=user.id,
                    entity_type="qualification",
                    entity_id=uuid.uuid4(),
                    storage_key=keys[name],
                    mime_type="application/pdf",
                    size_bytes=1,
                    sha256="0" * 64,
                )
            )
        db.commit()
        assert uploads.cleanup_orphans(db, storage, now) == 2
        assert uploads.cleanup_orphans(db, storage, now) == 0
    assert {k for k, _ in storage.objects()} == {keys["orphan_23h59"], keys["row_24h01"], keys["row_year"]}
