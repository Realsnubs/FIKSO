"""Ed25519 signing of catalogue packages (R-CAT-17).

Production holds the only private key; staging holds public keys and can verify but never sign. Keys travel
as base64 of the raw 32-byte Ed25519 key. The private key is only read from settings as a SecretStr and is
never returned, logged or written into a package.
"""

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

KEY_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


class InvalidKeyError(ValueError):
    """Malformed key material (raised at startup by the settings check)."""


def _raw(value: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidKeyError("key is not valid base64") from exc
    if len(raw) != 32:
        raise InvalidKeyError("Ed25519 keys are 32 bytes")
    return raw


def load_private_key(value: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_raw(value))


def load_public_key(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_raw(value))


def sign(private_key: str, message: bytes) -> str:
    return base64.b64encode(load_private_key(private_key).sign(message)).decode()


def verify(public_key: str, message: bytes, signature: str) -> bool:
    try:
        load_public_key(public_key).verify(base64.b64decode(signature, validate=True), message)
    except (InvalidSignature, binascii.Error, ValueError):
        return False
    return True


def generate_keypair() -> tuple[str, str]:
    """Return (private, public) as base64 raw keys. Used only by the operator CLI."""
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode()
