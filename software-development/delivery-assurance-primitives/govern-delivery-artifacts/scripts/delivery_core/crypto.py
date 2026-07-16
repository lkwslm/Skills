"""Ed25519 signing primitives with no unsigned compatibility mode."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Union

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError as exc:  # pragma: no cover - exercised in dependency-isolation tests
    raise RuntimeError(
        "required dependency unavailable: cryptography with Ed25519 support"
    ) from exc


PrivateKeyInput = Union[Ed25519PrivateKey, bytes, bytearray, str, Path]
PublicKeyInput = Union[Ed25519PublicKey, bytes, bytearray, str, Path]


class SignatureError(ValueError):
    """A key, signature, or key binding is invalid."""


def _read_key_bytes(source: Union[bytes, bytearray, str, Path]) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    try:
        return Path(source).read_bytes()
    except OSError as exc:
        raise SignatureError("cannot read key: " + str(exc)) from exc


def load_private_key(source: PrivateKeyInput) -> Ed25519PrivateKey:
    if isinstance(source, Ed25519PrivateKey):
        return source
    try:
        key = serialization.load_pem_private_key(_read_key_bytes(source), password=None)
    except (TypeError, ValueError) as exc:
        raise SignatureError("invalid unencrypted PEM private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise SignatureError("private key is not Ed25519")
    return key


def load_public_key(source: PublicKeyInput) -> Ed25519PublicKey:
    if isinstance(source, Ed25519PublicKey):
        return source
    try:
        key = serialization.load_pem_public_key(_read_key_bytes(source))
    except (TypeError, ValueError) as exc:
        raise SignatureError("invalid PEM public key") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise SignatureError("public key is not Ed25519")
    return key


def public_key_fingerprint(source: PublicKeyInput) -> str:
    key = load_public_key(source)
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def private_key_fingerprint(source: PrivateKeyInput) -> str:
    return public_key_fingerprint(load_private_key(source).public_key())


def encode_signature(signature: bytes) -> str:
    return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def decode_signature(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise SignatureError("signature must be non-empty base64url text")
    if "=" in encoded:
        raise SignatureError("signature must use unpadded base64url encoding")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        decoded = base64.b64decode(
            encoded + padding, altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise SignatureError("signature is not valid base64url") from exc
    if len(decoded) != 64:
        raise SignatureError("Ed25519 signature must contain 64 bytes")
    return decoded


def sign(source: PrivateKeyInput, message: bytes) -> str:
    if not isinstance(message, bytes):
        raise SignatureError("signed message must be bytes")
    return encode_signature(load_private_key(source).sign(message))


def verify(source: PublicKeyInput, message: bytes, signature: str) -> None:
    if not isinstance(message, bytes):
        raise SignatureError("verified message must be bytes")
    try:
        load_public_key(source).verify(decode_signature(signature), message)
    except InvalidSignature as exc:
        raise SignatureError("Ed25519 signature verification failed") from exc


def private_key_pem(source: PrivateKeyInput) -> bytes:
    return load_private_key(source).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def public_key_pem(source: PublicKeyInput) -> bytes:
    return load_public_key(source).public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
