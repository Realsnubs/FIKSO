"""Admin access to qualification evidence files (step 4.4.3, R-MST-15, Q-27)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.db import SessionLocal
from app.integrations.storage import get_storage, new_key
from app.models import Attachment, AuditLog, MasterProfile, Qualification, User
from tests.conftest import auth, register
from tests.files import PDF, PNG

UNSAFE_NAME = '../../etc/passwd" onload=x.pdf'


@dataclass
class M:
    id: uuid.UUID
    user_id: uuid.UUID
    h: dict[str, str]


@dataclass
class Fx:
    admin: dict[str, str]
    admin_id: uuid.UUID
    qualification_id: uuid.UUID
    other_qualification_id: uuid.UUID


@pytest.fixture
def fx(client: TestClient, admin_token: str) -> Iterator[Fx]:
    with SessionLocal() as db:
        first = Qualification(name="Elektrodrošība", status="active", requires_document=True)
        second = Qualification(name="Gāzes iekārtas", status="active", requires_document=True)
        db.add_all([first, second])
        db.commit()
        admin_id = db.scalar(select(User.id).where(User.role == "admin"))
        assert admin_id is not None
        yield Fx(auth(admin_token), admin_id, first.id, second.id)


def _master(client: TestClient) -> M:
    body = register(client, "master")
    user_id = uuid.UUID(body["user"]["id"])
    with SessionLocal() as db:
        master_id = db.scalar(select(MasterProfile.id).where(MasterProfile.user_id == user_id))
    assert master_id is not None
    return M(master_id, user_id, auth(body["access_token"]))


def _submit(
    client: TestClient, master: M, qualification_id: uuid.UUID, *files: tuple[str, bytes, str]
) -> Any:
    resp = client.post(
        "/api/v1/master/qualifications",
        data={"qualification_id": str(qualification_id)},
        files=[("files", f) for f in files or [("a.pdf", PDF, "application/pdf")]],
        headers=master.h,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(master_id: Any, submission_id: Any, file_id: Any) -> str:
    return f"/api/v1/admin/masters/{master_id}/qualifications/{submission_id}/files/{file_id}"


def _access_log() -> list[AuditLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(["attachment.viewed", "attachment.downloaded"]))
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )


def _attachment(file_id: Any) -> Attachment:
    with SessionLocal() as db:
        row = db.get(Attachment, uuid.UUID(str(file_id)))
        assert row is not None
        return row


def _raw_attachment(owner_user_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID) -> uuid.UUID:
    """A stored object with a row that the upload API would never create (wrong type or owner)."""
    key = new_key()
    get_storage().put(key, PDF)
    with SessionLocal() as db:
        row = Attachment(
            owner_user_id=owner_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            storage_key=key,
            mime_type="application/pdf",
            size_bytes=len(PDF),
            sha256="0" * 64,
        )
        db.add(row)
        db.commit()
        return row.id


# --- access -------------------------------------------------------------------------------------------------


def test_only_admins(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    body = _submit(client, master, fx.qualification_id)
    url = _url(master.id, body["id"], body["files"][0]["id"])
    customer = auth(register(client, "client")["access_token"])
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    for headers in (master.h, customer):  # the owning master too: they use their own route
        resp = client.get(url, headers=headers)
        assert resp.status_code == 403 and "content-disposition" not in resp.headers
    assert _access_log() == []


def test_admin_downloads_and_views_with_logging_and_safe_headers(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    body = _submit(
        client, master, fx.qualification_id, (UNSAFE_NAME, PDF, "image/png"), ("b.png", PNG, "x/y")
    )
    files = {f["mime_type"]: f["id"] for f in body["files"]}
    pdf_id, png_id = files["application/pdf"], files["image/png"]

    download = client.get(_url(master.id, body["id"], pdf_id), headers=fx.admin)
    assert download.status_code == 200 and download.content == PDF
    # The type comes from the content, never the uploaded name or Content-Type; the name is the file UUID.
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == f'attachment; filename="{pdf_id}.pdf"'
    assert download.headers["content-length"] == str(len(PDF))
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["cache-control"] == "no-store, private"
    assert "content-security-policy" not in download.headers
    assert [entry.action for entry in _access_log()] == ["attachment.downloaded"]

    view = client.get(_url(master.id, body["id"], png_id), params={"mode": "view"}, headers=fx.admin)
    assert view.status_code == 200 and view.content == PNG
    assert view.headers["content-type"] == "image/png"
    assert view.headers["content-disposition"] == f'inline; filename="{png_id}.png"'
    assert view.headers["content-security-policy"] == "sandbox; default-src 'none'; img-src 'self'"
    assert view.headers["x-content-type-options"] == "nosniff"

    log = _access_log()
    assert [(e.action, e.actor_id, str(e.entity_id), e.entity_type) for e in log] == [
        ("attachment.downloaded", fx.admin_id, pdf_id, "attachment"),
        ("attachment.viewed", fx.admin_id, png_id, "attachment"),
    ]
    assert log[1].after == {"submission_id": body["id"], "master_id": str(master.id), "mode": "view"}

    pdf = _attachment(pdf_id)
    for response in (download, view):
        exposed = str(response.headers).lower()
        assert pdf.storage_key not in exposed and pdf.sha256 not in exposed and "passwd" not in exposed
    assert all(pdf.storage_key not in str(e.after) for e in log)


@pytest.mark.parametrize("mode", ["raw", "", "VIEW", "inline"])
def test_unsupported_mode(client: TestClient, fx: Fx, mode: str) -> None:
    master = _master(client)
    body = _submit(client, master, fx.qualification_id)
    resp = client.get(
        _url(master.id, body["id"], body["files"][0]["id"]), params={"mode": mode}, headers=fx.admin
    )
    assert resp.status_code == 422 and "content-disposition" not in resp.headers
    assert _access_log() == []


# --- resolution ---------------------------------------------------------------------------------------------


def test_every_id_swap_is_the_same_404(client: TestClient, fx: Fx) -> None:
    owner, other = _master(client), _master(client)
    mine = _submit(client, owner, fx.qualification_id)
    second = _submit(client, owner, fx.other_qualification_id)
    theirs = _submit(client, other, fx.qualification_id)
    sub, file = mine["id"], mine["files"][0]["id"]
    attempts = [
        (other.id, sub, file),  # wrong master for this submission
        (uuid.uuid4(), sub, file),  # unknown master
        (owner.user_id, sub, file),  # user ID instead of master ID
        (owner.id, second["id"], file),  # the owner's other submission
        (owner.id, uuid.uuid4(), file),  # unknown submission
        (owner.id, sub, second["files"][0]["id"]),  # the owner's file of another submission
        (owner.id, sub, theirs["files"][0]["id"]),  # another master's file
        (other.id, theirs["id"], file),  # another master's submission with this file
        (owner.id, sub, uuid.uuid4()),  # unknown file
        (owner.id, sub, uuid.UUID(_attachment(file).storage_key)),  # the storage key used as a file ID
    ]
    for master_id, sub_id, file_id in attempts:
        resp = client.get(_url(master_id, sub_id, file_id), headers=fx.admin)
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "FILE_NOT_FOUND"), (
            master_id,
            sub_id,
        )
    assert client.get(_url(owner.id, sub, "x"), headers=fx.admin).status_code == 422
    assert _access_log() == []
    # The right combination still works for both masters.
    assert client.get(_url(owner.id, sub, file), headers=fx.admin).status_code == 200
    assert (
        client.get(_url(other.id, theirs["id"], theirs["files"][0]["id"]), headers=fx.admin).status_code
        == 200
    )


def test_wrong_entity_type_or_owner_is_not_served(client: TestClient, fx: Fx) -> None:
    master, other = _master(client), _master(client)
    body = _submit(client, master, fx.qualification_id)
    submission = uuid.UUID(body["id"])
    # Same entity ID, but bound to another entity type.
    wrong_type = _raw_attachment(master.user_id, "request", submission)
    # Right type and submission, but owned by another user (impossible through the API; guarded anyway).
    wrong_owner = _raw_attachment(other.user_id, "qualification", submission)
    for file_id in (wrong_type, wrong_owner):
        resp = client.get(_url(master.id, submission, file_id), headers=fx.admin)
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "FILE_NOT_FOUND")
    assert _access_log() == []


def test_missing_object_is_404_and_not_logged(client: TestClient, fx: Fx) -> None:
    master = _master(client)
    body = _submit(client, master, fx.qualification_id)
    file_id = body["files"][0]["id"]
    get_storage().delete(_attachment(file_id).storage_key)
    for mode in ("view", "download"):
        resp = client.get(_url(master.id, body["id"], file_id), params={"mode": mode}, headers=fx.admin)
        assert (resp.status_code, resp.json()["error"]["code"]) == (404, "FILE_UNAVAILABLE")
    assert _access_log() == []


def test_deleted_account_documents_are_not_served(client: TestClient, fx: Fx) -> None:
    """Like the admin master detail, a deleted account's records are not shown (retention: Q-12/Q-27)."""
    master = _master(client)
    body = _submit(client, master, fx.qualification_id)
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == master.user_id).values(deleted_at=datetime.now(UTC)))
        db.commit()
    resp = client.get(_url(master.id, body["id"], body["files"][0]["id"]), headers=fx.admin)
    assert (resp.status_code, resp.json()["error"]["code"]) == (404, "FILE_NOT_FOUND")
    assert _access_log() == []


def test_master_route_is_unchanged(client: TestClient, fx: Fx) -> None:
    """The admin route adds nothing to masters: the owner still reads only through their own route."""
    owner, other = _master(client), _master(client)
    body = _submit(client, owner, fx.qualification_id)
    own = f"/api/v1/master/qualifications/{body['id']}/files/{body['files'][0]['id']}"
    assert client.get(own, headers=owner.h).status_code == 200
    assert client.get(own, headers=other.h).status_code == 404
    assert client.get(own, headers=fx.admin).status_code == 403
    with SessionLocal() as db:
        actors = db.scalars(select(AuditLog.actor_id).where(AuditLog.action == "attachment.downloaded")).all()
        assert actors == [owner.user_id]
        assert (
            db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_id == fx.admin_id)) == 0
        )
