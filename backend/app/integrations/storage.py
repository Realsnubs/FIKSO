"""Private object storage for uploaded files (ARCHITECTURE §6b "Evidence files").

The interface has no URL generation on purpose: files are only ever streamed by the API after an
ownership/admin check, so no public or pre-signed link can exist (Q-27). Keys are random and contain no user
data.
"""

import io
import os
import re
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from botocore.exceptions import ClientError

from app.core.config import get_settings

KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def new_key() -> str:
    return secrets.token_hex(16)


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete(self, key: str) -> None: ...

    def objects(self) -> Iterator[tuple[str, datetime]]:
        """Every stored key with its write time (used only by the orphan cleanup)."""
        ...


class LocalStorage:
    """Directory storage for development and tests. The directory must not be served by any web server."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        # Only our own random keys are accepted, so a key can never point outside the root.
        if not KEY_PATTERN.match(key):
            raise ValueError("invalid storage key")
        return self.root / key

    def put(self, key: str, data: bytes) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".part")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def check(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def objects(self) -> Iterator[tuple[str, datetime]]:
        if not self.root.exists():
            return
        for path in self.root.iterdir():
            if KEY_PATTERN.match(path.name):
                yield path.name, datetime.fromtimestamp(path.stat().st_mtime, UTC)


class S3Storage:
    """S3-compatible object storage (AWS, Hetzner, Scaleway, MinIO …), one bucket per store.

    Nothing is ever made public at the bucket: public images are still served through the API, so a withdrawn
    consent takes effect at once.
    """

    def __init__(self, bucket: str, client: Any, encrypt: bool) -> None:
        self.bucket = bucket
        self.client = client
        self.encrypt = encrypt

    def put(self, key: str, data: bytes) -> None:
        if not KEY_PATTERN.match(key):
            raise ValueError("invalid storage key")
        extra = {"ServerSideEncryption": "AES256"} if self.encrypt else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def open(self, key: str) -> BinaryIO:
        if not KEY_PATTERN.match(key):
            raise ValueError("invalid storage key")
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError(key) from exc
            raise
        return _Body(body)  # type: ignore[return-value]

    def delete(self, key: str) -> None:
        if KEY_PATTERN.match(key):
            self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def objects(self) -> Iterator[tuple[str, datetime]]:
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket):
            for item in page.get("Contents", []):
                if KEY_PATTERN.match(item["Key"]):
                    yield item["Key"], item["LastModified"]

    def check(self) -> None:
        """Readiness: the bucket is reachable with these credentials."""
        self.client.head_bucket(Bucket=self.bucket)


class _Body(io.RawIOBase):
    """botocore's streaming body as a binary file object that streams in chunks."""

    def __init__(self, body: Any) -> None:
        self._body = body

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        return bytes(self._body.read(None if size < 0 else size))

    def __iter__(self) -> Iterator[bytes]:
        yield from self._body.iter_chunks(64 * 1024)

    def close(self) -> None:
        self._body.close()
        super().close()


def _s3_client() -> Any:
    import boto3
    from botocore.config import Config

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None,
        aws_secret_access_key=(
            settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None
        ),
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
            signature_version="s3v4",
        ),
    )


@lru_cache
def get_storage() -> Storage:
    """Private files (evidence documents, request photos): only ever streamed after an access check."""
    settings = get_settings()
    if settings.storage_backend == "s3":
        assert settings.s3_private_bucket
        return S3Storage(settings.s3_private_bucket, _s3_client(), settings.s3_server_side_encryption)
    return LocalStorage(settings.storage_local_dir)


@lru_cache
def get_public_storage() -> Storage:
    """Processed public catalogue images only (OQ-10). Separate from the private store by construction."""
    settings = get_settings()
    if settings.storage_backend == "s3":
        assert settings.s3_public_bucket
        return S3Storage(settings.s3_public_bucket, _s3_client(), settings.s3_server_side_encryption)
    return LocalStorage(settings.storage_public_dir)
