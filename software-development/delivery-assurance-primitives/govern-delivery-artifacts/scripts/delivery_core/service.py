"""Trusted replay and the sole mutation service used by deliveryctl."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import stat
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Sequence

from .authority import resolve_and_verify, verify_digest
from .canonical import canonical_json_bytes, loads_strict, read_bounded, sha256_hex
from .crypto import private_key_fingerprint, public_key_fingerprint
from .ledger import Revision, build_signed_event, generation_directories, load_committed_events, read_head, verify_event
from .reducer import apply_operations, empty_state
from .transaction import commit_event, ensure_store_confinement, inspect_store


class ServiceError(ValueError):
    """The external trust anchor or replayed domain state is invalid."""


@dataclass
class ReplayResult:
    revision: Revision
    state: dict[str, Any]
    event_keys: dict[str, bytes]


def ensure_external_path(repo: Path, path: Path, label: str) -> Path:
    """Require an authority/key file to be outside the governed repository and link-free."""
    repo = repo.resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ServiceError(f"{label} must be an absolute path outside the repository")
    current = candidate
    while True:
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ServiceError(f"cannot inspect {label}: {exc}") from exc
        else:
            if os.path.islink(current) or bool(
                getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ServiceError(f"{label} must not contain a symlink or reparse point")
        if current.parent == current:
            break
        current = current.parent
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo)
    except ValueError:
        return resolved
    except OSError as exc:
        raise ServiceError(f"cannot resolve {label}: {exc}") from exc
    raise ServiceError(f"{label} must be outside the governed repository")


def _trusted_write_time(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ServiceError("write timestamp must be valid UTC") from exc
    if not value.endswith("Z") or parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ServiceError("write timestamp must be UTC and end in Z")
    if abs((datetime.now(timezone.utc) - parsed).total_seconds()) > 300:
        raise ServiceError("write timestamp differs from the trusted system clock by more than 300 seconds")


def _validate_provider_observation(observed: Any, record: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "profile_id", "profile_hash", "provider", "mode", "adapter_version",
        "version", "version_source", "artifact_root", "configuration", "authorities", "id_mapping",
        "capabilities", "command_entrypoints", "runtime", "observations", "trust",
    }
    if not isinstance(observed, dict) or set(observed) != required or observed.get("schema_version") != "1.0":
        raise ServiceError("provider observation fields or schema_version are invalid")
    observed_hash = observed.get("profile_hash")
    if not isinstance(observed_hash, str) or observed_hash != sha256_hex(canonical_json_bytes({key: value for key, value in observed.items() if key != "profile_hash"})):
        raise ServiceError("provider observation profile_hash is invalid")
    runtime = observed.get("runtime")
    trust = observed.get("trust")
    collections_valid = (
        isinstance(observed.get("authorities"), dict) and bool(observed["authorities"])
        and isinstance(observed.get("id_mapping"), dict) and bool(observed["id_mapping"])
        and isinstance(observed.get("capabilities"), list) and bool(observed["capabilities"])
        and isinstance(observed.get("command_entrypoints"), dict) and bool(observed["command_entrypoints"])
        and isinstance(observed.get("observations"), dict) and bool(observed["observations"])
    )
    if not collections_valid or not isinstance(runtime, dict) or not isinstance(trust, dict):
        raise ServiceError("provider observation native evidence is incomplete")
    expected_executable = "openspec" if record["provider"] == "openspec" else "specify"
    expected_version_args = ["--version"] if record["provider"] == "openspec" else ["version"]
    if (
        observed.get("profile_id") != record["profile_id"]
        or observed.get("provider") != record["provider"]
        or observed.get("mode") != "native"
        or observed.get("version") != record["provider_version"]
        or observed.get("id_mapping") != record["id_mapping"]
        or not all(isinstance(observed.get(field), str) and observed[field] for field in ("adapter_version", "version_source", "artifact_root", "configuration"))
        or runtime.get("executable") != expected_executable
        or set(runtime) not in ({"executable", "resolved_path", "sha256", "version_args", "observed_version", "manifest", "manifest_sha256"}, {"executable", "resolved_path", "sha256", "version_args", "observed_version", "manifest", "manifest_sha256", "interpreter", "interpreter_sha256", "entrypoint", "entrypoint_sha256"})
        or runtime.get("observed_version") != record["provider_version"]
        or not isinstance(runtime.get("resolved_path"), str) or not runtime["resolved_path"]
        or not isinstance(runtime.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", runtime["sha256"]) is None
        or not isinstance(runtime.get("manifest"), str) or not runtime["manifest"]
        or not isinstance(runtime.get("manifest_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", runtime["manifest_sha256"]) is None
        or runtime.get("version_args") != expected_version_args
        or trust.get("level") != "trusted"
        or not isinstance(trust.get("reasons"), list) or not trust["reasons"]
    ):
        raise ServiceError("provider observation differs from the signed provider profile")
    if "interpreter" in runtime and (not isinstance(runtime.get("interpreter_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", runtime["interpreter_sha256"]) is None or not isinstance(runtime.get("entrypoint"), str) or not isinstance(runtime.get("entrypoint_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", runtime["entrypoint_sha256"]) is None):
        raise ServiceError("provider observation interpreter or entrypoint pin is invalid")


def validate_prepared_generation(
    repo: Path,
    trust_root_path: Path,
    expected_revision: Revision,
    current: ReplayResult,
    *,
    repository_map: Mapping[str, Path],
    git_executable: Path | None = None,
    git_sha256: str | None = None,
    git_manifest: Path | None = None,
    git_manifest_sha256: str | None = None,
) -> None:
    """Validate reducer semantics and authority before recovery makes an event visible."""
    trust_root_path = ensure_external_path(repo, trust_root_path, "external trust root")
    delivery = repo / ".delivery"
    stages_root = delivery / ".transactions"
    stages = [] if not stages_root.exists() else [path for path in stages_root.iterdir() if path.is_dir() and path.name.endswith(".prepared")]
    orphans = [path for path in generation_directories(delivery) if int(path.name.split("-", 1)[0]) > expected_revision.sequence]
    if len(stages) + len(orphans) != 1:
        raise ServiceError("recovery requires exactly one prepared generation")
    prepared = (stages + orphans)[0]
    event = _load_json(prepared / "event.json")
    if not isinstance(event, dict) or event.get("event_id") in current.event_keys:
        raise ServiceError("prepared event is invalid or reuses an event ID")
    actors = [item for item in current.state["trust_policy"]["actors"] if item["actor_id"] == event.get("actor_id")]
    if len(actors) != 1:
        raise ServiceError("prepared event actor is not uniquely trusted")
    public_key = actors[0]["public_key_pem"].encode("utf-8")
    verify_event(event, public_key, expected_sequence=expected_revision.sequence + 1, expected_previous_hash=expected_revision.event_hash)
    _trusted_write_time(event["occurred_at"])
    committed_events = load_committed_events(delivery, expected_revision)
    if committed_events:
        previous_time = datetime.fromisoformat(committed_events[-1]["occurred_at"].replace("Z", "+00:00"))
        prepared_time = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        if prepared_time <= previous_time:
            raise ServiceError("prepared event timestamp is not strictly after the committed head")
    if event.get("event_type") != "delivery_transaction" or set(event.get("payload", {})) != {"operations"}:
        raise ServiceError("prepared event is not a strict delivery transaction")
    state = apply_operations(
        current.state, event["payload"]["operations"], actor_id=event["actor_id"],
        signer_fingerprint=public_key_fingerprint(public_key), sequence=event["sequence"],
        event_id=event["event_id"], at=event["occurred_at"],
    )
    trust_root = load_trust_root(trust_root_path)
    if state["trust_policy"]["ledger_id"] != trust_root["ledger_id"] or state["trust_policy"]["root_key_fingerprint"] != trust_root["current_root_fingerprint"]:
        raise ServiceError("prepared event trust policy differs from the external trust root")
    if read_bounded(prepared / "views" / "state.json") != canonical_json_bytes(state):
        raise ServiceError("prepared state view differs from deterministic reducer output")
    pending_blobs: dict[str, bytes] = {}
    blobs_root = prepared / "views" / "blobs" / "sha256"
    if blobs_root.exists():
        for path in blobs_root.iterdir():
            if not path.is_file() or len(path.name) != 64:
                raise ServiceError("prepared generation contains an invalid blob")
            pending_blobs[path.name] = read_bounded(path)
    _verify_state_authorities(
        state, repository_map=repository_map, delivery_root=delivery,
        pending_blobs=pending_blobs, git_executable=git_executable, git_sha256=git_sha256,
        git_manifest=git_manifest, git_manifest_sha256=git_manifest_sha256,
    )


def _verify_state_authorities(
    state: Mapping[str, Any],
    *,
    repository_map: Mapping[str, Path],
    delivery_root: Path,
    pending_blobs: Mapping[str, bytes] | None = None,
    git_executable: Path | None = None,
    git_sha256: str | None = None,
    git_manifest: Path | None = None,
    git_manifest_sha256: str | None = None,
) -> None:
    profiles = state["provider_profiles"]
    profile_map = {key: {"digest": value["digest"], "record": value["record"]} for key, value in profiles.items()}
    pending = pending_blobs or {}

    def committed_blob_exists(digest_value: str) -> bool:
        from .ledger import read_head

        head = read_head(delivery_root)
        return any(
            (generation / "views" / "blobs" / "sha256" / digest_value).is_file()
            for generation in generation_directories(delivery_root)
            if int(generation.name.split("-", 1)[0]) <= head.sequence
        )

    referenced_pending: set[str] = set()

    def pending_material(authority: Mapping[str, Any], expected: Mapping[str, Any]) -> bytes | None:
        if authority.get("kind") != "delivery_blob":
            return None
        authority_digest = authority.get("digest")
        if authority_digest != expected:
            raise ServiceError("delivery_blob authority digest differs from the governed record digest")
        digest_value = expected["value"]
        if digest_value not in pending:
            return None
        if committed_blob_exists(digest_value):
            raise ServiceError("pending blob duplicates content already committed to the ledger")
        data = pending[digest_value]
        verify_digest(data, expected)
        referenced_pending.add(digest_value)
        return data

    def verify(authority: Mapping[str, Any], digest: Mapping[str, Any]) -> None:
        if pending_material(authority, digest) is not None:
            return
        resolve_and_verify(
            authority, digest, repository_map=repository_map,
            delivery_root=delivery_root, provider_profiles=profile_map,
            git_executable=git_executable, git_sha256=git_sha256,
            git_manifest=git_manifest, git_manifest_sha256=git_manifest_sha256,
        )

    def material(authority: Mapping[str, Any], digest: Mapping[str, Any]) -> bytes:
        data = pending_material(authority, digest)
        if data is not None:
            return data
        return resolve_and_verify(
            authority, digest, repository_map=repository_map,
            delivery_root=delivery_root, provider_profiles=profile_map,
            git_executable=git_executable, git_sha256=git_sha256,
            git_manifest=git_manifest, git_manifest_sha256=git_manifest_sha256,
        )

    for item in profiles.values():
        record = item["record"]
        observation_authority = record["observation_authority"]
        observation_digest = observation_authority["digest"]
        raw = material(observation_authority, observation_digest)
        try:
            observed = loads_strict(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ServiceError("provider observation blob is not strict JSON") from exc
        _validate_provider_observation(observed, record)

    for artifact in state["artifacts"].values():
        verify(artifact["authority"], artifact["digest"])
    for item in state["evidence"].values():
        evidence = item["record"]
        verify(evidence["log_authority"], evidence["log_authority"]["digest"])
    for item in state["migrations"].values():
        migration = item["record"]
        verify(
            {"schema_version": "1.0", "kind": "delivery_blob", "digest": migration["blob_digest"]},
            migration["blob_digest"],
        )
    if set(pending) != referenced_pending:
        raise ServiceError("pending blobs contain unreferenced or mismatched content")


def _load_json(path: Path) -> Any:
    try:
        return loads_strict(read_bounded(path))
    except (OSError, ValueError) as exc:
        raise ServiceError(f"cannot read {path}: {exc}") from exc


def load_trust_root(path: Path) -> dict[str, Any]:
    root = _load_json(path)
    required = {"schema_version", "ledger_id", "current_root_fingerprint", "keys"}
    if not isinstance(root, dict) or set(root) != required or root.get("schema_version") != "1.0":
        raise ServiceError("trust root fields or schema_version are invalid")
    if not isinstance(root["ledger_id"], str) or not root["ledger_id"]:
        raise ServiceError("trust root ledger_id is required")
    if not isinstance(root["keys"], list) or not root["keys"]:
        raise ServiceError("trust root must contain key history")
    seen: set[str] = set()
    for key in root["keys"]:
        if not isinstance(key, dict) or set(key) != {"fingerprint", "public_key_pem", "valid_from_sequence", "valid_through_sequence"}:
            raise ServiceError("trust-root key history entry is invalid")
        fingerprint = public_key_fingerprint(key["public_key_pem"].encode("utf-8"))
        if key["fingerprint"] != fingerprint or fingerprint in seen:
            raise ServiceError("trust-root key fingerprint is invalid or duplicated")
        if not isinstance(key["valid_from_sequence"], int) or key["valid_from_sequence"] < 1:
            raise ServiceError("trust-root key valid_from_sequence is invalid")
        through = key["valid_through_sequence"]
        if through is not None and (not isinstance(through, int) or through < key["valid_from_sequence"]):
            raise ServiceError("trust-root key valid_through_sequence is invalid")
        seen.add(fingerprint)
    if root["current_root_fingerprint"] not in seen:
        raise ServiceError("current root fingerprint is absent from key history")
    return root


def _root_key_at(trust_root: Mapping[str, Any], fingerprint: str, sequence: int) -> bytes:
    for item in trust_root["keys"]:
        if item["fingerprint"] != fingerprint:
            continue
        through = item["valid_through_sequence"]
        if item["valid_from_sequence"] <= sequence and (through is None or sequence <= through):
            return item["public_key_pem"].encode("utf-8")
    raise ServiceError(f"root key {fingerprint} is not externally trusted at sequence {sequence}")


def _manifest_verified(generation: Path, expected_parent: Revision, state: Mapping[str, Any]) -> None:
    manifest = _load_json(generation / "manifest.json")
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "generation", "parent_revision", "files"}:
        raise ServiceError(f"invalid generation manifest: {generation.name}")
    if manifest["schema_version"] != "1.0" or manifest["generation"] != generation.name or manifest["parent_revision"] != str(expected_parent):
        raise ServiceError(f"generation manifest identity mismatch: {generation.name}")
    files = manifest["files"]
    if not isinstance(files, dict) or not {"event.json", "views/state.json"}.issubset(files):
        raise ServiceError(f"generation must contain an event and state view: {generation.name}")
    extras = set(files) - {"event.json", "views/state.json"}
    for relative in extras:
        parts = relative.split("/")
        if len(parts) != 4 or parts[:3] != ["views", "blobs", "sha256"] or len(parts[3]) != 64:
            raise ServiceError(f"generation contains an unsupported derived file: {relative}")
    actual = {path.relative_to(generation).as_posix() for path in generation.rglob("*") if path.is_file() and path.name != "manifest.json"}
    if actual != set(files):
        raise ServiceError(f"generation contains unmanifested or missing files: {generation.name}")
    for relative, expected_hash in files.items():
        data = read_bounded(generation / relative)
        if not isinstance(expected_hash, str) or sha256_hex(data) != expected_hash:
            raise ServiceError(f"generation file digest mismatch: {generation.name}/{relative}")
        if relative.startswith("views/blobs/sha256/") and relative.rsplit("/", 1)[1] != expected_hash:
            raise ServiceError(f"content-addressed blob name mismatch: {generation.name}/{relative}")
    if read_bounded(generation / "views" / "state.json") != canonical_json_bytes(state):
        raise ServiceError(f"derived state view differs from deterministic replay: {generation.name}")


def _ensure_store_surface(repo: Path, *, allow_legacy_source: bool = False, allow_legacy_backup: bool = False) -> None:
    if (repo / ".specflow").exists() and not allow_legacy_source:
        raise ServiceError("LEGACY_LEDGER_PRESENT: run the explicit migrate-specflow command")
    backups = [repo / ".specflow-legacy-migration", repo / ".delivery-legacy-migration"]
    if any(path.exists() for path in backups) and not allow_legacy_backup:
        raise ServiceError("LEGACY_MIGRATION_INCOMPLETE: finish the explicit migration before normal operations")
    delivery = repo / ".delivery"
    if not delivery.exists():
        return
    ensure_store_confinement(delivery)
    allowed = {"HEAD.json", "generations", "blobs", ".transactions", ".lock"}
    unexpected = sorted(path.name for path in delivery.iterdir() if path.name not in allowed)
    if unexpected:
        raise ServiceError("unversioned delivery records are present: " + ", ".join(unexpected))


def replay(
    repo: Path,
    trust_root_path: Path,
    expected_head: Revision,
    *,
    verify_authorities: bool = False,
    repository_map: Mapping[str, Path] | None = None,
    allow_recovery: bool = False,
    allow_legacy_source: bool = False,
    allow_legacy_backup: bool = False,
    git_executable: Path | None = None,
    git_sha256: str | None = None,
    git_manifest: Path | None = None,
    git_manifest_sha256: str | None = None,
) -> ReplayResult:
    repo = repo.resolve()
    trust_root_path = ensure_external_path(repo, trust_root_path, "external trust root")
    _ensure_store_surface(repo, allow_legacy_source=allow_legacy_source, allow_legacy_backup=allow_legacy_backup)
    delivery = repo / ".delivery"
    trust_root = load_trust_root(trust_root_path)
    current = read_head(delivery)
    if current != expected_head:
        raise ServiceError(f"current HEAD {current} does not match external expected head {expected_head}")
    events = load_committed_events(delivery, current)
    if not events:
        raise ServiceError("delivery ledger has no signed genesis")
    generations = generation_directories(delivery)[:current.sequence]
    state = empty_state()
    event_keys: dict[str, bytes] = {}
    seen_event_ids: set[str] = set()
    previous = Revision.genesis()
    previous_time: datetime | None = None
    for event, generation in zip(events, generations):
        if event.get("event_id") in seen_event_ids:
            raise ServiceError(f"duplicate event_id: {event.get('event_id')}")
        seen_event_ids.add(event.get("event_id"))
        if event.get("event_type") != "delivery_transaction" or set(event.get("payload", {})) != {"operations"}:
            raise ServiceError("event is not a strict delivery transaction")
        operations = event["payload"]["operations"]
        if not isinstance(operations, list) or not operations:
            raise ServiceError("delivery transaction has no operations")
        if event["sequence"] == 1:
            fingerprint = event["signature"]["key_id"]
            public_key = _root_key_at(trust_root, fingerprint, 1)
            genesis = True
        else:
            actors = [item for item in state["trust_policy"]["actors"] if item["actor_id"] == event["actor_id"]]
            if len(actors) != 1:
                raise ServiceError(f"event actor is not uniquely trusted: {event['actor_id']}")
            public_key = actors[0]["public_key_pem"].encode("utf-8")
            fingerprint = public_key_fingerprint(public_key)
            genesis = False
        revision = verify_event(event, public_key, expected_sequence=previous.sequence + 1, expected_previous_hash=previous.event_hash)
        event_time = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        if previous_time is not None and event_time <= previous_time:
            raise ServiceError("signed event timestamps are not strictly increasing")
        state = apply_operations(
            state,
            operations,
            actor_id=event["actor_id"],
            signer_fingerprint=fingerprint,
            sequence=event["sequence"],
            event_id=event["event_id"],
            at=event["occurred_at"],
            genesis=genesis,
        )
        if state["trust_policy"]["ledger_id"] != trust_root["ledger_id"]:
            raise ServiceError("ledger trust policy is bound to a different external ledger_id")
        _root_key_at(trust_root, state["trust_policy"]["root_key_fingerprint"], event["sequence"])
        _manifest_verified(generation, previous, state)
        event_keys[event["event_id"]] = public_key
        previous = revision
        previous_time = event_time
    _root_key_at(trust_root, state["trust_policy"]["root_key_fingerprint"], expected_head.sequence)
    key_resolver = lambda event: event_keys[event["event_id"]]
    if not allow_recovery:
        inspect_store(delivery, expected_revision=expected_head, key_resolver=key_resolver)
    if verify_authorities:
        _verify_state_authorities(
            state, repository_map=repository_map or {}, delivery_root=delivery,
            git_executable=git_executable, git_sha256=git_sha256,
            git_manifest=git_manifest, git_manifest_sha256=git_manifest_sha256,
        )
    return ReplayResult(expected_head, state, event_keys)


def initialize(
    repo: Path,
    trust_root_path: Path,
    policy: Mapping[str, Any],
    root_private_key: Path,
    *,
    actor_id: str,
    event_id: str,
    operation_id: str,
    at: str,
    extra_operations: Sequence[Mapping[str, Any]] = (),
    extra_views: Mapping[str, bytes] | None = None,
    allow_legacy_source: bool = False,
    allow_legacy_backup: bool = False,
) -> Revision:
    _trusted_write_time(at)
    repo = repo.resolve()
    trust_root_path = ensure_external_path(repo, trust_root_path, "external trust root")
    ensure_external_path(repo, root_private_key, "root signing key")
    if (repo / ".delivery").exists() or ((repo / ".specflow").exists() and not allow_legacy_source):
        raise ServiceError("repository already contains delivery data; use an explicit migration command")
    trust_root = load_trust_root(trust_root_path)
    signer = private_key_fingerprint(root_private_key)
    if signer != trust_root["current_root_fingerprint"]:
        raise ServiceError("root signing key does not match the external trust root")
    operation = {"schema_version": "1.0", "operation_id": operation_id, "type": "trust_policy_initialized", "payload": {"policy": dict(policy)}}
    operations = [operation, *list(extra_operations)]
    state = apply_operations(empty_state(), operations, actor_id=actor_id, signer_fingerprint=signer, sequence=1, event_id=event_id, at=at, genesis=True)
    if state["trust_policy"]["ledger_id"] != trust_root["ledger_id"]:
        raise ServiceError("initial policy ledger_id differs from the external trust root")
    event = build_signed_event(sequence=1, previous_event_hash=Revision.genesis().event_hash, event_id=event_id, event_type="delivery_transaction", occurred_at=at, actor_id=actor_id, payload={"operations": operations}, private_key=root_private_key)
    root_public_key = _root_key_at(trust_root, signer, 1)
    views: dict[str, Any] = {"state.json": state}
    pending_blobs: dict[str, bytes] = {}
    for name, content in (extra_views or {}).items():
        parts = name.split("/")
        if len(parts) != 3 or parts[:2] != ["blobs", "sha256"] or len(parts[2]) != 64 or not isinstance(content, (bytes, bytearray)):
            raise ServiceError("initial extra views must be content-addressed blob bytes")
        pending_blobs[parts[2]] = bytes(content)
        views[name] = bytes(content)
    _verify_state_authorities(
        state, repository_map={}, delivery_root=repo / ".delivery", pending_blobs=pending_blobs,
    )
    revision = commit_event(repo / ".delivery", expected_revision=Revision.genesis(), event=event, key_resolver=lambda _: root_public_key, views=views)
    if not (repo / ".specflow").exists():
        replay(repo, trust_root_path, revision, allow_legacy_backup=allow_legacy_backup)
    return revision


def commit(
    repo: Path,
    trust_root_path: Path,
    expected_revision: Revision,
    operations: Sequence[Mapping[str, Any]],
    signing_key: Path,
    *,
    actor_id: str,
    event_id: str,
    at: str,
    blobs: Mapping[str, bytes] | None = None,
    repository_map: Mapping[str, Path] | None = None,
    git_executable: Path | None = None,
    git_sha256: str | None = None,
    git_manifest: Path | None = None,
    git_manifest_sha256: str | None = None,
) -> Revision:
    _trusted_write_time(at)
    trust_root_path = ensure_external_path(repo, trust_root_path, "external trust root")
    ensure_external_path(repo, signing_key, "signing key")
    result = replay(repo, trust_root_path, expected_revision)
    if event_id in result.event_keys:
        raise ServiceError("event_id already exists in the signed ledger")
    trust_root = load_trust_root(trust_root_path)
    signer = private_key_fingerprint(signing_key)
    new_sequence = expected_revision.sequence + 1
    state = apply_operations(result.state, list(operations), actor_id=actor_id, signer_fingerprint=signer, sequence=new_sequence, event_id=event_id, at=at)
    if state["trust_policy"]["ledger_id"] != trust_root["ledger_id"]:
        raise ServiceError("resulting trust policy does not match the protected external trust root")
    old_root = result.state["trust_policy"]["root_key_fingerprint"]
    external_root = trust_root["current_root_fingerprint"]
    if old_root == external_root:
        if state["trust_policy"]["root_key_fingerprint"] != external_root:
            raise ServiceError("root rotation requires the external trust root to be prepared first")
    else:
        rotations = [item for item in operations if item.get("type") == "trust_policy_rotated"]
        if len(operations) != 1 or len(rotations) != 1 or state["trust_policy"]["root_key_fingerprint"] != external_root:
            raise ServiceError("external root is ahead; only the exact pending trust rotation may commit")
        old_entries = [item for item in trust_root["keys"] if item["fingerprint"] == old_root]
        new_entries = [item for item in trust_root["keys"] if item["fingerprint"] == external_root]
        if (
            len(old_entries) != 1 or old_entries[0]["valid_through_sequence"] != expected_revision.sequence
            or len(new_entries) != 1 or new_entries[0]["valid_from_sequence"] != new_sequence
        ):
            raise ServiceError("external root rotation sequence boundaries are invalid")
    _root_key_at(trust_root, state["trust_policy"]["root_key_fingerprint"], new_sequence)
    _verify_state_authorities(
        state,
        repository_map=repository_map or {},
        delivery_root=repo / ".delivery",
        pending_blobs=blobs,
        git_executable=git_executable,
        git_sha256=git_sha256,
        git_manifest=git_manifest,
        git_manifest_sha256=git_manifest_sha256,
    )
    event = build_signed_event(sequence=new_sequence, previous_event_hash=expected_revision.event_hash, event_id=event_id, event_type="delivery_transaction", occurred_at=at, actor_id=actor_id, payload={"operations": list(operations)}, private_key=signing_key)
    key_map: Dict[str, bytes] = dict(result.event_keys)
    actors = [item for item in result.state["trust_policy"]["actors"] if item["actor_id"] == actor_id]
    if len(actors) != 1 or actors[0]["key_fingerprint"] != signer:
        raise ServiceError("signing key is not bound to the actor in the current trust policy")
    key_map[event_id] = actors[0]["public_key_pem"].encode("utf-8")
    views: dict[str, Any] = {"state.json": state}
    for digest, content in (blobs or {}).items():
        if sha256_hex(content) != digest:
            raise ServiceError(f"blob content does not match its digest: {digest}")
        views[f"blobs/sha256/{digest}"] = content
    revision = commit_event(repo / ".delivery", expected_revision=expected_revision, event=event, key_resolver=lambda item: key_map[item["event_id"]], views=views)
    replay(
        repo, trust_root_path, revision, verify_authorities=True,
        repository_map=repository_map or {}, git_executable=git_executable, git_sha256=git_sha256,
        git_manifest=git_manifest, git_manifest_sha256=git_manifest_sha256,
    )
    return revision
