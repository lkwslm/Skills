"""Signed, hash-chained event ledger and externally anchored HEAD handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from .canonical import canonical_json_bytes, loads_strict, read_bounded, sha256_hex
from .crypto import (
    PrivateKeyInput,
    PublicKeyInput,
    private_key_fingerprint,
    public_key_fingerprint,
    sign,
    verify,
)


SCHEMA_VERSION = "1.0"
ZERO_HASH = "0" * 64
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GENERATION_PATTERN = re.compile(r"^(\d{20})-([0-9a-f]{64})$")


class LedgerError(ValueError):
    """The ledger, an event, or its external head anchor is invalid."""


def _require_utc(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerError("occurred_at must be a valid UTC date-time") from exc
    if not value.endswith("Z") or parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise LedgerError("occurred_at must be a UTC date-time ending in Z")


@dataclass(frozen=True)
class Revision:
    sequence: int
    event_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise LedgerError("revision sequence must be an integer")
        if self.sequence < 0:
            raise LedgerError("revision sequence cannot be negative")
        if not HASH_PATTERN.fullmatch(self.event_hash):
            raise LedgerError("revision event_hash must be lowercase SHA-256")
        if self.sequence == 0 and self.event_hash != ZERO_HASH:
            raise LedgerError("genesis revision must use the zero hash")

    @classmethod
    def genesis(cls) -> "Revision":
        return cls(0, ZERO_HASH)

    @classmethod
    def parse(cls, value: str) -> "Revision":
        if not isinstance(value, str) or ":" not in value:
            raise LedgerError("revision must use SEQUENCE:HASH")
        sequence, event_hash = value.split(":", 1)
        if not sequence.isdigit():
            raise LedgerError("revision sequence must be a non-negative integer")
        return cls(int(sequence), event_hash)

    def __str__(self) -> str:
        return "{}:{}".format(self.sequence, self.event_hash)


def generation_name(revision: Revision) -> str:
    if revision.sequence == 0:
        raise LedgerError("genesis has no generation directory")
    return "{:020d}-{}".format(revision.sequence, revision.event_hash)


def _unsigned_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in event.items() if key not in {"signature", "event_hash"}}


def _event_without_hash(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_hash"}


def build_signed_event(
    *,
    sequence: int,
    previous_event_hash: str,
    event_id: str,
    event_type: str,
    occurred_at: str,
    actor_id: str,
    payload: Mapping[str, Any],
    private_key: PrivateKeyInput,
) -> Dict[str, Any]:
    """Create an Ed25519-signed event whose hash includes its signature."""
    if sequence < 1:
        raise LedgerError("event sequence must be positive")
    expected_previous = ZERO_HASH if sequence == 1 else previous_event_hash
    if previous_event_hash != expected_previous or not HASH_PATTERN.fullmatch(previous_event_hash):
        raise LedgerError("event previous_event_hash is invalid")
    for name, value in {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor_id": actor_id,
    }.items():
        if not isinstance(value, str) or not value:
            raise LedgerError(name + " must be non-empty text")
    if not isinstance(payload, Mapping):
        raise LedgerError("event payload must be an object")
    _require_utc(occurred_at)
    event: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "previous_event_hash": previous_event_hash,
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor_id": actor_id,
        "payload": dict(payload),
    }
    key_id = private_key_fingerprint(private_key)
    event["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": sign(private_key, canonical_json_bytes(event)),
    }
    event["event_hash"] = sha256_hex(canonical_json_bytes(event))
    return event


def verify_event(
    event: Mapping[str, Any],
    public_key: PublicKeyInput,
    *,
    expected_sequence: int,
    expected_previous_hash: str,
) -> Revision:
    required = {
        "schema_version",
        "sequence",
        "previous_event_hash",
        "event_id",
        "event_type",
        "occurred_at",
        "actor_id",
        "payload",
        "signature",
        "event_hash",
    }
    if not isinstance(event, Mapping) or set(event) != required:
        raise LedgerError("event fields do not match the signed event contract")
    if event.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError("unsupported event schema_version")
    if event.get("sequence") != expected_sequence:
        raise LedgerError("event sequence is not contiguous")
    if event.get("previous_event_hash") != expected_previous_hash:
        raise LedgerError("event previous hash does not match the ledger head")
    if not isinstance(event.get("payload"), Mapping):
        raise LedgerError("event payload must be an object")
    for name in ("event_id", "event_type", "occurred_at", "actor_id"):
        if not isinstance(event.get(name), str) or not event[name]:
            raise LedgerError(name + " must be non-empty text")
    _require_utc(event["occurred_at"])
    signature = event.get("signature")
    if not isinstance(signature, Mapping) or set(signature) != {"algorithm", "key_id", "value"}:
        raise LedgerError("event signature fields are invalid")
    if signature.get("algorithm") != "ed25519":
        raise LedgerError("event signature algorithm must be ed25519")
    expected_key_id = public_key_fingerprint(public_key)
    if signature.get("key_id") != expected_key_id:
        raise LedgerError("event signing key does not match the trusted public key")
    event_hash = event.get("event_hash")
    if not isinstance(event_hash, str) or not HASH_PATTERN.fullmatch(event_hash):
        raise LedgerError("event_hash must be lowercase SHA-256")
    calculated_hash = sha256_hex(canonical_json_bytes(_event_without_hash(event)))
    if calculated_hash != event_hash:
        raise LedgerError("event_hash does not match signed event content")
    try:
        verify(
            public_key,
            canonical_json_bytes(_unsigned_event(event)),
            signature.get("value"),
        )
    except ValueError as exc:
        raise LedgerError(str(exc)) from exc
    return Revision(expected_sequence, event_hash)


KeyResolver = Callable[[Mapping[str, Any]], PublicKeyInput]


def validate_chain(
    events: Iterable[Mapping[str, Any]],
    key_resolver: KeyResolver,
    *,
    expected_head: Revision,
) -> Revision:
    """Verify every event against externally supplied actor trust and HEAD."""
    current = Revision.genesis()
    for event in events:
        try:
            public_key = key_resolver(event)
        except Exception as exc:
            raise LedgerError("trusted key resolution failed: " + str(exc)) from exc
        current = verify_event(
            event,
            public_key,
            expected_sequence=current.sequence + 1,
            expected_previous_hash=current.event_hash,
        )
    if current != expected_head:
        raise LedgerError(
            "ledger head {} does not match external expected head {}".format(
                current, expected_head
            )
        )
    return current


def head_document(revision: Revision, manifest_hash: str) -> Dict[str, Any]:
    if revision.sequence == 0:
        raise LedgerError("genesis is represented by an absent HEAD")
    if not HASH_PATTERN.fullmatch(manifest_hash):
        raise LedgerError("manifest_hash must be lowercase SHA-256")
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": revision.sequence,
        "event_hash": revision.event_hash,
        "generation": generation_name(revision),
        "manifest_hash": manifest_hash,
    }


def read_head(delivery_dir: Path) -> Revision:
    path = Path(delivery_dir) / "HEAD.json"
    if not path.exists():
        return Revision.genesis()
    try:
        value = loads_strict(read_bounded(path))
    except OSError as exc:
        raise LedgerError("cannot read HEAD: " + str(exc)) from exc
    required = {"schema_version", "sequence", "event_hash", "generation", "manifest_hash"}
    if not isinstance(value, dict) or set(value) != required:
        raise LedgerError("HEAD fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError("unsupported HEAD schema_version")
    revision = Revision(value.get("sequence"), value.get("event_hash"))
    if value.get("generation") != generation_name(revision):
        raise LedgerError("HEAD generation does not match its revision")
    if not isinstance(value.get("manifest_hash"), str) or not HASH_PATTERN.fullmatch(value["manifest_hash"]):
        raise LedgerError("HEAD manifest_hash must be lowercase SHA-256")
    return revision


def read_head_document(delivery_dir: Path) -> Optional[Dict[str, Any]]:
    revision = read_head(delivery_dir)
    if revision.sequence == 0:
        return None
    return loads_strict(read_bounded(Path(delivery_dir) / "HEAD.json"))


def generation_directories(delivery_dir: Path) -> List[Path]:
    root = Path(delivery_dir) / "generations"
    if not root.exists():
        return []
    result: List[Path] = []
    for path in root.iterdir():
        if not path.is_dir() or GENERATION_PATTERN.fullmatch(path.name) is None:
            raise LedgerError("invalid generation entry: " + path.name)
        result.append(path)
    return sorted(result, key=lambda item: item.name)


def load_committed_events(delivery_dir: Path, head: Revision) -> List[Dict[str, Any]]:
    if head.sequence == 0:
        return []
    directories = generation_directories(delivery_dir)
    committed = [
        path for path in directories
        if int(GENERATION_PATTERN.fullmatch(path.name).group(1)) <= head.sequence
    ]
    if len(committed) != head.sequence:
        raise LedgerError("committed generation sequence has gaps or duplicates")
    events: List[Dict[str, Any]] = []
    for expected_sequence, directory in enumerate(committed, 1):
        match = GENERATION_PATTERN.fullmatch(directory.name)
        if int(match.group(1)) != expected_sequence:
            raise LedgerError("committed generation sequence is not contiguous")
        try:
            event = loads_strict(read_bounded(directory / "event.json"))
        except OSError as exc:
            raise LedgerError("cannot read committed event: " + str(exc)) from exc
        if not isinstance(event, dict) or event.get("event_hash") != match.group(2):
            raise LedgerError("generation name does not match its event")
        events.append(event)
    if events[-1].get("event_hash") != head.event_hash:
        raise LedgerError("HEAD does not identify the final committed event")
    return events
