"""Deterministic canonicalization used by hashes and signatures.

``delivery-json-v1`` deliberately supports a smaller data model than general
JSON.  Floating-point numbers and duplicate or normalization-colliding object
keys are rejected so two implementations cannot silently sign different byte
representations of the same apparent value.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
from typing import Any, Dict, Iterable, Tuple, Union


DELIVERY_JSON_V1 = "delivery-json-v1"
RAW_V1 = "raw-v1"
UTF8_NFC_LF_V1 = "utf8-nfc-lf-v1"
SUPPORTED_CANONICALIZATIONS = frozenset(
    {DELIVERY_JSON_V1, RAW_V1, UTF8_NFC_LF_V1}
)
MAX_LEDGER_FILE_BYTES = 50 * 1024 * 1024
MAX_INTEGER_DIGITS = 1000


class CanonicalizationError(ValueError):
    """Input cannot be represented by a supported canonical format."""


def _reject_float(token: str) -> None:
    raise CanonicalizationError(
        "delivery-json-v1 rejects floating-point numbers: " + token
    )


def _reject_constant(token: str) -> None:
    raise CanonicalizationError(
        "delivery-json-v1 rejects non-finite numbers: " + token
    )


def _bounded_int(token: str) -> int:
    digits = token.lstrip("+-")
    if len(digits) > MAX_INTEGER_DIGITS:
        raise CanonicalizationError("integer exceeds the delivery protocol digit limit")
    return int(token)


def _strict_object(pairs: Iterable[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def loads_strict(data: Union[str, bytes, bytearray]) -> Any:
    """Parse UTF-8 JSON while rejecting ambiguous JSON constructs."""
    if isinstance(data, (bytes, bytearray)):
        try:
            text = bytes(data).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError("JSON is not valid UTF-8") from exc
    elif isinstance(data, str):
        text = data
    else:
        raise CanonicalizationError("JSON input must be text or bytes")
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_int=_bounded_int,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise CanonicalizationError("invalid JSON: " + str(exc)) from exc


def _normalize(value: Any, where: str = "$") -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError(where + ": floating-point values are forbidden")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item, where + "[]") for item in value]
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(where + ": object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise CanonicalizationError(
                    where + ": object keys collide after NFC normalization"
                )
            result[normalized_key] = _normalize(item, where + "." + normalized_key)
        return result
    raise CanonicalizationError(
        where + ": unsupported value type " + type(value).__name__
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a Python value as canonical ``delivery-json-v1`` bytes."""
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonicalize(data: Union[Any, bytes, bytearray, str], version: str) -> bytes:
    """Canonicalize bytes/text/JSON with an explicitly named algorithm."""
    if version == RAW_V1:
        if not isinstance(data, (bytes, bytearray)):
            raise CanonicalizationError("raw-v1 input must be bytes")
        return bytes(data)
    if version == UTF8_NFC_LF_V1:
        if isinstance(data, (bytes, bytearray)):
            try:
                text = bytes(data).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CanonicalizationError("text is not valid UTF-8") from exc
        elif isinstance(data, str):
            text = data
        else:
            raise CanonicalizationError("utf8-nfc-lf-v1 input must be text or bytes")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return unicodedata.normalize("NFC", text).encode("utf-8")
    if version == DELIVERY_JSON_V1:
        value = loads_strict(data) if isinstance(data, (str, bytes, bytearray)) else data
        return canonical_json_bytes(value)
    raise CanonicalizationError("unsupported canonicalization: " + str(version))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bounded(path: Any, *, limit: int = MAX_LEDGER_FILE_BYTES) -> bytes:
    """Read a regular ledger file with a strict size bound."""
    target = os.fspath(path)
    try:
        metadata = os.lstat(target)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise CanonicalizationError("ledger file is missing, non-regular, or too large")
        with open(target, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise CanonicalizationError("cannot read ledger file: " + str(exc)) from exc
    if len(data) > limit:
        raise CanonicalizationError("ledger file exceeds its size limit")
    return data


def canonical_digest(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(value))
