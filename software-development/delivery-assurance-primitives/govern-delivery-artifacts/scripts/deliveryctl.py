#!/usr/bin/env python3
"""Create, mutate, migrate, recover, and validate the signed delivery ledger."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
from datetime import datetime, timezone
import re
from typing import Any

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from delivery_core.authority import AuthorityError, digest_bytes, run_trusted_git
    from delivery_core.canonical import canonical_json_bytes, loads_strict, read_bounded
    from delivery_core.crypto import private_key_fingerprint, private_key_pem, public_key_fingerprint, public_key_pem
    from delivery_core.ledger import Revision, read_head
    from delivery_core.events import OperationError
    from delivery_core.migrations import MigrationError, archive_legacy, build_import_operation
    from delivery_core.permissions import actor_record, path_covered
    from delivery_core.progress import build_progress
    from delivery_core.provider import ProviderSyncError, build_provider_operations
    from delivery_core.reducer import ReducerError, apply_operations
    from delivery_core.service import ServiceError, commit, initialize, load_trust_root, replay, validate_prepared_generation
    from delivery_core.transaction import RecoveryRequired, RevisionConflict, TransactionError, recover_transaction, discard_incomplete_builds
except (ImportError, RuntimeError) as exc:  # no dependency-free or unsigned mode
    print(json.dumps({"ok": False, "code": "DEPENDENCY_UNAVAILABLE", "errors": [str(exc)]}), file=sys.stderr)
    raise SystemExit(3)


class CliInputError(ValueError):
    pass


def _remove_legacy_tree(path: Path) -> None:
    from delivery_core.migrations import _is_link_or_reparse

    if _is_link_or_reparse(path):
        raise MigrationError(f"legacy cleanup target must not be a symlink or reparse point: {path}")
    for child in path.rglob("*"):
        if _is_link_or_reparse(child):
            raise MigrationError(f"legacy cleanup contains a symlink or reparse point: {child}")
    shutil.rmtree(path)


def _json_file(path: Path) -> Any:
    try:
        return loads_strict(read_bounded(path))
    except (OSError, ValueError) as exc:
        raise CliInputError(f"cannot read {path}: {exc}") from exc


def _create_windows_private(path: Path, data: bytes) -> None:
    """Create with a protected DACL attached before writing any private bytes."""
    import ctypes
    from ctypes import wintypes
    descriptor = ctypes.c_void_p()
    sddl = "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)"
    if not ctypes.windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise CliInputError(f"cannot construct a protected Windows DACL for {path}")
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]
    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    kernel = ctypes.windll.kernel32
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SecurityAttributes), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        kernel.LocalFree(descriptor)
        raise CliInputError(f"cannot securely create {path}: {error}")
    try:
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))
        handle = invalid
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if handle != invalid:
            kernel.CloseHandle(handle)
        kernel.LocalFree(descriptor)
    _protect_windows_file(path)
    _flush_directory_durable(path.parent)


def _flush_directory_durable(path: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000, 0x00000007, None, 3, 0x02000000 | 0x80000000, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            raise CliInputError(f"cannot open directory for durable flush: {path}: {ctypes.get_last_error()}")
        try:
            if not kernel.FlushFileBuffers(handle):
                raise CliInputError(f"cannot flush directory metadata: {path}: {ctypes.get_last_error()}")
        finally:
            kernel.CloseHandle(handle)
        return
    if os.name == "posix":
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_new(path: Path, data: bytes, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if private and os.name == "nt":
        try:
            _create_windows_private(path, data)
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise
        return
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise CliInputError(f"refusing to overwrite {path}: {exc}") from exc
    _flush_directory_durable(path.parent)


def _replace_durable(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".next")
    _write_new(temporary, data, private=True)
    try:
        os.replace(temporary, path)
        if os.name == "nt":
            _protect_windows_file(path)
        _flush_directory_durable(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _protect_windows_file(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    # OW is the Windows Owner Rights SID; it avoids a token lookup race while
    # still granting only the creating user's owner rights. Inheritance is
    # explicitly disabled by the D:P control flag.
    sddl = "D:P(A;;FA;;;OW)(A;;FA;;;SY)(A;;FA;;;BA)"
    descriptor = ctypes.c_void_p()
    if not ctypes.windll.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise CliInputError(f"cannot construct a protected Windows DACL for {path}")
    try:
        if not ctypes.windll.advapi32.SetFileSecurityW(str(path), 0x00000004 | 0x80000000, descriptor):
            raise CliInputError(f"cannot apply a protected Windows DACL to {path}")
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)

    needed = wintypes.DWORD()
    ctypes.windll.advapi32.GetFileSecurityW(str(path), 0x00000004, None, 0, ctypes.byref(needed))
    security = ctypes.create_string_buffer(needed.value)
    if not ctypes.windll.advapi32.GetFileSecurityW(str(path), 0x00000004, security, needed, ctypes.byref(needed)):
        raise CliInputError(f"cannot verify the protected Windows DACL on {path}")
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not ctypes.windll.advapi32.GetSecurityDescriptorControl(security, ctypes.byref(control), ctypes.byref(revision)) or not control.value & 0x1000:
        raise CliInputError(f"Windows DACL inheritance remains enabled on {path}")
    rendered = wintypes.LPWSTR()
    if not ctypes.windll.advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        security, 1, 0x00000004, ctypes.byref(rendered), None
    ):
        raise CliInputError(f"cannot render the protected Windows DACL on {path}")
    try:
        principals = set(re.findall(r";;;([^;)]+)\)", rendered.value))
    finally:
        ctypes.windll.kernel32.LocalFree(rendered)
    if principals != {"OW", "SY", "BA"}:
        raise CliInputError(f"protected Windows DACL contains unexpected principals on {path}")


def _emit(ok: bool, code: str, **payload: Any) -> None:
    print(json.dumps({"ok": ok, "code": code, **payload}, ensure_ascii=False, sort_keys=True))


def _repository_map(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise CliInputError("repository map must use URI=LOCAL_CHECKOUT")
        uri, local = raw.split("=", 1)
        if not uri or not local or uri in result:
            raise CliInputError("repository map URI and checkout must be non-empty and unique")
        result[uri] = Path(local)
    return result


def _blobs(paths: list[Path]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    total = 0
    for path in paths:
        try:
            data = read_bounded(path, limit=max(0, 50 * 1024 * 1024 - total))
        except (OSError, ValueError) as exc:
            raise CliInputError(f"cannot read blob {path}: {exc}") from exc
        total += len(data)
        digest = digest_bytes(data, "raw-v1")["value"]
        if digest in result:
            raise CliInputError(f"duplicate blob content: {path}")
        result[digest] = data
    return result


def command_bootstrap(args: argparse.Namespace) -> int:
    key = Ed25519PrivateKey.generate()
    private = private_key_pem(key)
    public = public_key_pem(key.public_key())
    fingerprint = public_key_fingerprint(public)
    root = {
        "schema_version": "1.0",
        "ledger_id": args.ledger_id,
        "current_root_fingerprint": fingerprint,
        "keys": [{
            "fingerprint": fingerprint,
            "public_key_pem": public.decode("ascii"),
            "valid_from_sequence": 1,
            "valid_through_sequence": None,
        }],
    }
    _write_new(args.private_key, private, private=True)
    _write_new(args.public_key, public)
    _write_new(args.trust_root, canonical_json_bytes(root), private=True)
    _emit(True, "TRUST_BOOTSTRAPPED", ledger_id=args.ledger_id, root_fingerprint=fingerprint)
    return 0


def command_generate_key(args: argparse.Namespace) -> int:
    key = Ed25519PrivateKey.generate()
    private = private_key_pem(key)
    public = public_key_pem(key.public_key())
    fingerprint = public_key_fingerprint(public)
    _write_new(args.private_key, private, private=True)
    _write_new(args.public_key, public)
    _emit(True, "ACTOR_KEY_GENERATED", key_fingerprint=fingerprint)
    return 0


def command_rotate_root(args: argparse.Namespace) -> int:
    expected = Revision.parse(args.expected_revision)
    current = load_trust_root(args.trust_root)
    old_fingerprint = private_key_fingerprint(args.old_signing_key)
    if old_fingerprint not in {item["fingerprint"] for item in current["keys"]}:
        raise ServiceError("old signing key is absent from the external trust history")
    try:
        new_public = read_bounded(args.new_public_key)
    except OSError as exc:
        raise CliInputError(f"cannot read new root public key: {exc}") from exc
    new_fingerprint = public_key_fingerprint(new_public)
    next_sequence = expected.sequence + 1
    policy = _json_file(args.policy)
    if not isinstance(policy, dict) or policy.get("root_key_fingerprint") != new_fingerprint:
        raise CliInputError("rotated policy must bind the new external root fingerprint")
    _trusted_now(args.at)
    current_result = replay(args.root, args.trust_root, expected)
    operation = [{
        "schema_version": "1.0", "operation_id": args.operation_id,
        "type": "trust_policy_rotated", "payload": {"policy": policy},
    }]
    apply_operations(
        current_result.state, operation, actor_id=args.actor_id, signer_fingerprint=old_fingerprint,
        sequence=next_sequence, event_id=args.event_id, at=args.at,
    )
    if current["current_root_fingerprint"] == old_fingerprint:
        if any(item["fingerprint"] == new_fingerprint for item in current["keys"]):
            raise ServiceError("new root key already exists in external trust history")
        rotated = json.loads(json.dumps(current))
        for item in rotated["keys"]:
            if item["fingerprint"] == old_fingerprint:
                if item["valid_through_sequence"] is not None:
                    raise ServiceError("old root key already has a closed validity interval")
                item["valid_through_sequence"] = expected.sequence
        rotated["keys"].append({
            "fingerprint": new_fingerprint,
            "public_key_pem": new_public.decode("ascii"),
            "valid_from_sequence": next_sequence,
            "valid_through_sequence": None,
        })
        rotated["current_root_fingerprint"] = new_fingerprint
        _replace_durable(args.trust_root, canonical_json_bytes(rotated))
    elif current["current_root_fingerprint"] != new_fingerprint:
        raise ServiceError("external trust root is in a different rotation state")
    revision = commit(
        args.root, args.trust_root, expected, operation, args.old_signing_key,
        actor_id=args.actor_id, event_id=args.event_id, at=args.at,
        repository_map=_repository_map(args.repository_map),
        git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    _emit(True, "ROOT_ROTATED", revision=str(revision), root_fingerprint=new_fingerprint)
    return 0


def command_init(args: argparse.Namespace) -> int:
    policy = _json_file(args.policy)
    if not isinstance(policy, dict):
        raise CliInputError("policy must be a JSON object")
    revision = initialize(args.root, args.trust_root, policy, args.root_signing_key, actor_id=args.actor_id, event_id=args.event_id, operation_id=args.operation_id, at=args.at)
    _emit(True, "INITIALIZED", revision=str(revision))
    return 0


def command_commit(args: argparse.Namespace) -> int:
    operations = _json_file(args.operations)
    if not isinstance(operations, list) or not operations:
        raise CliInputError("operations must be a non-empty JSON array")
    revision = commit(
        args.root, args.trust_root, Revision.parse(args.expected_revision), operations, args.signing_key,
        actor_id=args.actor_id, event_id=args.event_id, at=args.at, blobs=_blobs(args.blob),
        repository_map=_repository_map(args.repository_map),
        git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    _emit(True, "COMMITTED", revision=str(revision))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    result = replay(
        args.root, args.trust_root, Revision.parse(args.expected_head), verify_authorities=True,
        repository_map=_repository_map(args.repository_map),
        git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    _emit(True, "VALID", revision=str(result.revision), artifacts=len(result.state["artifacts"]), operations=len(result.state["seen_operation_ids"]))
    return 0


def command_status(args: argparse.Namespace) -> int:
    result = replay(
        args.root, args.trust_root, Revision.parse(args.expected_head), verify_authorities=True,
        repository_map=_repository_map(args.repository_map),
        git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    payload = {
        "revision": str(result.revision),
        "progress": build_progress(result.state),
    }
    if not args.progress_only:
        payload["state"] = result.state
    _emit(True, "STATUS", **payload)
    return 0


def command_observe_provider(args: argparse.Namespace) -> int:
    raw = _json_file(args.profile)
    if isinstance(raw, dict) and "ok" in raw:
        if raw.get("ok") is not True or not isinstance(raw.get("profile"), dict):
            raise CliInputError("detector output does not contain a successful provider profile")
        observed = raw["profile"]
    else:
        raise CliInputError("provider profile must be successful detector JSON output")
    expected = Revision.parse(args.expected_revision)
    repository_map = _repository_map(args.repository_map)
    head = str(run_trusted_git(
        args.root, args.git_executable, args.git_sha256, "rev-parse", "HEAD",
        manifest_path=args.git_manifest, manifest_sha256=args.git_manifest_sha256,
    )).strip()
    if head != args.commit:
        raise ServiceError("provider observation commit must equal the checkout HEAD")
    artifact_root = observed.get("artifact_root")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ProviderSyncError("provider observation lacks an artifact root")
    root_path = PurePosixPath(artifact_root)
    if root_path.is_absolute() or any(part in {"", ".", ".."} for part in root_path.parts):
        raise ProviderSyncError("provider artifact root is unsafe")
    provider_changes = str(run_trusted_git(
        args.root, args.git_executable, args.git_sha256, "status", "--porcelain=v1",
        "--untracked-files=all", "--", artifact_root,
        manifest_path=args.git_manifest, manifest_sha256=args.git_manifest_sha256,
    )).strip()
    if provider_changes:
        raise ServiceError(f"provider artifact root differs from the pinned checkout HEAD: {provider_changes}")
    current = replay(
        args.root, args.trust_root, expected, verify_authorities=True,
        repository_map=repository_map, git_executable=args.git_executable,
        git_sha256=args.git_sha256, git_manifest=args.git_manifest,
        git_manifest_sha256=args.git_manifest_sha256,
    )
    operations, observation, counts = build_provider_operations(
        current.state, observed, repository_uri=args.repository_uri, commit=args.commit,
        at=args.at, operation_id_prefix=args.operation_id_prefix,
    )
    if not operations:
        _emit(True, "PROVIDER_UNCHANGED", revision=str(current.revision), **counts)
        return 0
    blobs = {}
    if observation is not None:
        digest = digest_bytes(observation, "raw-v1")["value"]
        blobs[digest] = observation
    revision = commit(
        args.root, args.trust_root, expected, operations, args.signing_key,
        actor_id=args.actor_id, event_id=args.event_id, at=args.at, blobs=blobs,
        repository_map=repository_map, git_executable=args.git_executable,
        git_sha256=args.git_sha256, git_manifest=args.git_manifest,
        git_manifest_sha256=args.git_manifest_sha256,
    )
    _emit(True, "PROVIDER_OBSERVED", revision=str(revision), **counts)
    return 0


def command_recover(args: argparse.Namespace) -> int:
    expected = Revision.parse(args.expected_revision)
    result = replay(args.root, args.trust_root, expected, allow_recovery=True)
    repository_map = _repository_map(args.repository_map)
    validate_prepared_generation(
        args.root.resolve(), args.trust_root, expected, result, repository_map=repository_map,
        git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    state = result.state

    def resolver(event: dict[str, Any]) -> bytes:
        known = result.event_keys.get(event["event_id"])
        if known is not None:
            return known
        actors = [item for item in state["trust_policy"]["actors"] if item["actor_id"] == event["actor_id"]]
        if len(actors) != 1:
            raise ServiceError("prepared event actor is not uniquely trusted")
        return actors[0]["public_key_pem"].encode("utf-8")

    revision = recover_transaction(args.root / ".delivery", expected_revision=expected, key_resolver=resolver)
    replay(
        args.root, args.trust_root, revision, verify_authorities=True,
        repository_map=repository_map, git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    _emit(True, "RECOVERED", revision=str(revision))
    return 0


def command_discard_build(args: argparse.Namespace) -> int:
    expected = Revision.parse(args.expected_revision)
    result = replay(args.root, args.trust_root, expected, allow_recovery=True)
    def resolver(event: dict[str, Any]) -> bytes:
        return result.event_keys[event["event_id"]]
    revision = discard_incomplete_builds(args.root / ".delivery", expected_revision=expected, key_resolver=resolver)
    replay(args.root, args.trust_root, revision)
    _emit(True, "BUILD_DISCARDED", revision=str(revision))
    return 0


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliInputError("--at must be a valid UTC date-time") from exc
    if not value.endswith("Z") or parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CliInputError("--at must be a UTC date-time ending in Z")
    return parsed


def _trusted_now(value: str) -> datetime:
    parsed = _utc(value)
    if abs((datetime.now(timezone.utc) - parsed).total_seconds()) > 300:
        raise CliInputError("--at differs from the trusted system clock by more than 300 seconds")
    return parsed


def command_authorize_diff(args: argparse.Namespace) -> int:
    mapping = _repository_map(args.repository_map)
    result = replay(
        args.root, args.trust_root, Revision.parse(args.expected_head), verify_authorities=True,
        repository_map=mapping, git_executable=args.git_executable, git_sha256=args.git_sha256,
        git_manifest=args.git_manifest, git_manifest_sha256=args.git_manifest_sha256,
    )
    checkout = mapping.get(args.repository_uri)
    if checkout is None:
        raise AuthorityError(f"no pinned checkout mapping for {args.repository_uri}")
    checkout = checkout.resolve()
    actor = actor_record(result.state, args.actor_id)
    now = _trusted_now(args.at)
    valid_from = _utc(actor["valid_from"])
    valid_until = _utc(actor["valid_until"]) if actor["valid_until"] is not None else None
    if now < valid_from or (valid_until is not None and now >= valid_until):
        raise ReducerError("actor key is outside its signed validity interval")
    revoked = actor["revoked_at_sequence"]
    if revoked is not None and result.revision.sequence >= revoked:
        raise ReducerError("actor key is revoked at the current signed revision")
    if "claim.write" not in actor["capabilities"] or args.environment not in actor["environments"]:
        raise ReducerError("actor no longer owns claim capability or the requested environment")
    if actor["key_fingerprint"] != result.state["trust_policy"]["root_key_fingerprint"] and set(actor["roles"]).isdisjoint({"implementer", "orchestrator"}):
        raise ReducerError("actor role cannot authorize an implementation diff")
    claim = result.state["claims"].get(args.claim_id)
    if claim is None or claim["status"] != "active":
        raise ReducerError("diff authorization requires an active claim")
    claim_record = claim["record"]
    if claim_record["holder_actor_id"] != args.actor_id or claim_record["lease_token"] != args.lease_token or claim_record["fencing_token"] != args.fencing_token:
        raise ReducerError("diff authorization claim actor, lease, or fencing token is stale")
    if now < _utc(claim_record["acquired_at"]) or _utc(claim_record["expires_at"]) <= now:
        raise ReducerError("diff authorization claim is expired")
    approvals = []
    for entry in result.state["approvals"].values():
        approval = entry["record"]
        if (
            approval["subject"] == claim_record["task"]
            and approval["run_id"] == args.run_id
            and approval["attempt_id"] == args.attempt_id
            and approval["base_commit"] == args.base
            and approval["target_commit"] == args.target
            and approval["environment"] == args.environment
            and approval["decision"] == "APPROVED"
            and _utc(approval["issued_at"]) <= now < _utc(approval["expires_at"])
        ):
            approvals.append(approval)
    if len(approvals) != 1:
        raise ReducerError("diff authorization requires exactly one current signed approval")
    commit_pattern = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
    if not commit_pattern.fullmatch(args.base) or not commit_pattern.fullmatch(args.target):
        raise CliInputError("diff base and target must be full Git commit IDs")
    git_options = {"manifest_path": args.git_manifest, "manifest_sha256": args.git_manifest_sha256}
    origin = run_trusted_git(checkout, args.git_executable, args.git_sha256, "remote", "get-url", "--all", "origin", **git_options)
    if args.repository_uri not in str(origin).splitlines():
        raise AuthorityError("mapped checkout origin does not match repository URI")
    for commit_id in (args.base, args.target):
        resolved = str(run_trusted_git(checkout, args.git_executable, args.git_sha256, "rev-parse", "--verify", f"{commit_id}^{{commit}}", **git_options)).strip()
        if resolved != commit_id:
            raise AuthorityError(f"Git commit is unavailable or not exact: {commit_id}")
    diff = bytes(run_trusted_git(
        checkout, args.git_executable, args.git_sha256,
        "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
        "--diff-filter=ACDMRTUXB", args.base, args.target,
        binary=True, **git_options,
    ))
    try:
        raw_paths = diff.split(b"\0")
        if raw_paths[-1] != b"":
            raise UnicodeError("missing NUL terminator")
        decoded_paths = [item.decode("utf-8", "strict") for item in raw_paths[:-1]]
    except UnicodeError as exc:
        raise AuthorityError("Git diff returned a non-UTF-8 or malformed path list") from exc
    if any(not path or "\\" in path or path != path.strip("\r\n") for path in decoded_paths):
        raise AuthorityError("Git diff returned an invalid repository path")
    changed = sorted(set(decoded_paths))
    approval_scope = approvals[0]["scope"]
    unauthorized = [path for path in changed if not path_covered(path, actor["path_scopes"]) or not path_covered(path, approval_scope)]
    if unauthorized:
        raise ReducerError("Git diff escapes signed actor/approval scope: " + ", ".join(unauthorized))
    _emit(True, "DIFF_AUTHORIZED", base=args.base, target=args.target, changed=changed, claim_id=args.claim_id, approval_id=approvals[0]["approval_id"])
    return 0


def _migration_material(source: Path, source_format: str, args: argparse.Namespace) -> tuple[bytes, dict[str, Any], str]:
    archive, untrusted = archive_legacy(source, source_format)
    operation, digest = build_import_operation(archive, untrusted, source_format=source_format, migration_id=args.migration_id, operation_id=args.migration_operation_id, imported_at=args.at)
    return archive, operation, digest


def _migration_init(repo: Path, source: Path, source_format: str, args: argparse.Namespace, *, allow_specflow: bool) -> Revision:
    archive, operation, digest = _migration_material(source, source_format, args)
    policy = _json_file(args.policy)
    if not isinstance(policy, dict):
        raise CliInputError("policy must be a JSON object")
    return initialize(
        repo, args.trust_root, policy, args.root_signing_key,
        actor_id=args.actor_id, event_id=args.event_id, operation_id=args.operation_id, at=args.at,
        extra_operations=[operation], extra_views={f"blobs/sha256/{digest}": archive},
        allow_legacy_source=allow_specflow, allow_legacy_backup=True,
    )


def command_migrate_specflow(args: argparse.Namespace) -> int:
    repo = args.root.resolve()
    source = repo / ".specflow"
    backup = repo / ".specflow-legacy-migration"
    if backup.exists():
        if not (repo / ".delivery").exists() or not args.expected_head:
            raise MigrationError("interrupted specflow migration requires the new ledger and --expected-head")
        result = replay(repo, args.trust_root, Revision.parse(args.expected_head), verify_authorities=True, allow_legacy_backup=True)
        recorded = result.state["migrations"].get(args.migration_id)
        if recorded is None or recorded["record"]["source_format"] != "legacy-specflow":
            raise MigrationError("signed ledger does not contain the requested specflow migration")
        _remove_legacy_tree(backup)
        replay(repo, args.trust_root, result.revision, verify_authorities=True)
        _emit(True, "MIGRATION_FINALIZED", revision=str(result.revision), source_format="legacy-specflow")
        return 0
    if not source.is_dir():
        raise MigrationError("legacy .specflow directory is absent")
    if (repo / ".delivery").exists():
        if not args.expected_head:
            raise CliInputError("finishing an interrupted migration requires --expected-head")
        raise MigrationError("legacy source and new ledger coexist without the atomic migration marker")
    archive_legacy(source, "legacy-specflow")
    source.rename(backup)
    try:
        revision = _migration_init(repo, backup, "legacy-specflow", args, allow_specflow=False)
    except Exception:
        if not source.exists() and backup.exists() and not (repo / ".delivery").exists():
            backup.rename(source)
        raise
    _remove_legacy_tree(backup)
    replay(repo, args.trust_root, revision, verify_authorities=True)
    _emit(True, "MIGRATED", revision=str(revision), source_format="legacy-specflow")
    return 0


def command_migrate_delivery(args: argparse.Namespace) -> int:
    repo = args.root.resolve()
    source = repo / ".delivery"
    backup = repo / ".delivery-legacy-migration"
    if backup.exists():
        if not source.exists() or not args.expected_head:
            raise MigrationError("interrupted delivery migration requires the new ledger and --expected-head")
        result = replay(repo, args.trust_root, Revision.parse(args.expected_head), verify_authorities=True, allow_legacy_backup=True)
        recorded = result.state["migrations"].get(args.migration_id)
        if recorded is None or recorded["record"]["source_format"] != "unversioned-delivery":
            raise MigrationError("signed ledger does not contain the requested migration")
        _remove_legacy_tree(backup)
        _emit(True, "MIGRATION_FINALIZED", revision=str(result.revision), source_format="unversioned-delivery")
        return 0
    if not source.is_dir() or (source / "HEAD.json").exists():
        raise MigrationError("unversioned .delivery directory is absent")
    archive_legacy(source, "unversioned-delivery")
    source.rename(backup)
    try:
        revision = _migration_init(repo, backup, "unversioned-delivery", args, allow_specflow=False)
    except Exception:
        if not source.exists() and backup.exists():
            backup.rename(source)
        raise
    _remove_legacy_tree(backup)
    replay(repo, args.trust_root, revision, verify_authorities=True)
    _emit(True, "MIGRATED", revision=str(revision), source_format="unversioned-delivery")
    return 0


def add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--trust-root", required=True, type=Path)
    parser.add_argument("--root-signing-key", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--at", required=True)


def add_git_runtime(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument("--git-executable", required=required, type=Path)
    parser.add_argument("--git-sha256", required=required)
    parser.add_argument("--git-manifest", required=required, type=Path)
    parser.add_argument("--git-manifest-sha256", required=required)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-trust", help="create an external Ed25519 trust root without overwriting files")
    bootstrap.add_argument("--ledger-id", required=True)
    bootstrap.add_argument("--private-key", required=True, type=Path)
    bootstrap.add_argument("--public-key", required=True, type=Path)
    bootstrap.add_argument("--trust-root", required=True, type=Path)
    bootstrap.set_defaults(handler=command_bootstrap)
    keygen = commands.add_parser("generate-key", help="create an operational Ed25519 actor key without overwriting files")
    keygen.add_argument("--private-key", required=True, type=Path)
    keygen.add_argument("--public-key", required=True, type=Path)
    keygen.set_defaults(handler=command_generate_key)
    rotate = commands.add_parser("rotate-root", help="prepare the external root and commit one exact fail-closed root rotation")
    rotate.add_argument("--root", required=True, type=Path)
    rotate.add_argument("--trust-root", required=True, type=Path)
    rotate.add_argument("--expected-revision", required=True)
    rotate.add_argument("--old-signing-key", required=True, type=Path)
    rotate.add_argument("--new-public-key", required=True, type=Path)
    rotate.add_argument("--policy", required=True, type=Path)
    rotate.add_argument("--actor-id", required=True)
    rotate.add_argument("--event-id", required=True)
    rotate.add_argument("--operation-id", required=True)
    rotate.add_argument("--at", required=True)
    rotate.add_argument("--repository-map", action="append", default=[])
    add_git_runtime(rotate)
    rotate.set_defaults(handler=command_rotate_root)
    init = commands.add_parser("init", help="create the root-signed ledger genesis")
    add_identity(init)
    init.set_defaults(handler=command_init)
    commit_parser = commands.add_parser("commit", help="commit a strict typed operation batch with HEAD CAS")
    commit_parser.add_argument("--root", required=True, type=Path)
    commit_parser.add_argument("--trust-root", required=True, type=Path)
    commit_parser.add_argument("--expected-revision", required=True)
    commit_parser.add_argument("--actor-id", required=True)
    commit_parser.add_argument("--signing-key", required=True, type=Path)
    commit_parser.add_argument("--event-id", required=True)
    commit_parser.add_argument("--at", required=True)
    commit_parser.add_argument("--operations", required=True, type=Path)
    commit_parser.add_argument("--blob", action="append", default=[], type=Path)
    commit_parser.add_argument("--repository-map", action="append", default=[])
    add_git_runtime(commit_parser)
    commit_parser.set_defaults(handler=command_commit)
    validate = commands.add_parser("validate", help="replay, re-hash authority, and compare the externally anchored head")
    validate.add_argument("--root", required=True, type=Path)
    validate.add_argument("--trust-root", required=True, type=Path)
    validate.add_argument("--expected-head", required=True)
    validate.add_argument("--repository-map", action="append", default=[])
    add_git_runtime(validate)
    validate.set_defaults(handler=command_validate)
    status = commands.add_parser("status", help="replay and return the verified resumable delivery state")
    status.add_argument("--root", required=True, type=Path)
    status.add_argument("--trust-root", required=True, type=Path)
    status.add_argument("--expected-head", required=True)
    status.add_argument("--progress-only", action="store_true")
    status.add_argument("--repository-map", action="append", default=[])
    add_git_runtime(status)
    status.set_defaults(handler=command_status)
    observe = commands.add_parser("observe-provider", help="sign one detector profile and reconcile its native artifacts")
    observe.add_argument("--root", required=True, type=Path)
    observe.add_argument("--trust-root", required=True, type=Path)
    observe.add_argument("--expected-revision", required=True)
    observe.add_argument("--actor-id", required=True)
    observe.add_argument("--signing-key", required=True, type=Path)
    observe.add_argument("--event-id", required=True)
    observe.add_argument("--operation-id-prefix", required=True)
    observe.add_argument("--at", required=True)
    observe.add_argument("--profile", required=True, type=Path)
    observe.add_argument("--repository-uri", required=True)
    observe.add_argument("--commit", required=True)
    observe.add_argument("--repository-map", action="append", required=True)
    add_git_runtime(observe, required=True)
    observe.set_defaults(handler=command_observe_provider)
    recover = commands.add_parser("recover", help="explicitly roll one complete prepared generation forward")
    recover.add_argument("--root", required=True, type=Path)
    recover.add_argument("--trust-root", required=True, type=Path)
    recover.add_argument("--expected-revision", required=True)
    recover.add_argument("--repository-map", action="append", default=[])
    add_git_runtime(recover)
    recover.set_defaults(handler=command_recover)
    discard = commands.add_parser("discard-building", help="explicitly discard only a pre-prepared crash residue")
    discard.add_argument("--root", required=True, type=Path)
    discard.add_argument("--trust-root", required=True, type=Path)
    discard.add_argument("--expected-revision", required=True)
    discard.set_defaults(handler=command_discard_build)
    diff = commands.add_parser("authorize-diff", help="verify a pinned Git diff against signed actor, approval, and fenced claim scope")
    diff.add_argument("--root", required=True, type=Path)
    diff.add_argument("--trust-root", required=True, type=Path)
    diff.add_argument("--expected-head", required=True)
    diff.add_argument("--repository-uri", required=True)
    diff.add_argument("--repository-map", action="append", required=True)
    add_git_runtime(diff, required=True)
    diff.add_argument("--base", required=True)
    diff.add_argument("--target", required=True)
    diff.add_argument("--actor-id", required=True)
    diff.add_argument("--claim-id", required=True)
    diff.add_argument("--lease-token", required=True)
    diff.add_argument("--fencing-token", required=True, type=int)
    diff.add_argument("--run-id", required=True)
    diff.add_argument("--attempt-id", required=True)
    diff.add_argument("--environment", required=True)
    diff.add_argument("--at", required=True)
    diff.set_defaults(handler=command_authorize_diff)
    for name, handler in (("migrate-specflow", command_migrate_specflow), ("migrate-delivery", command_migrate_delivery)):
        migrate = commands.add_parser(name, help="one-shot signed migration; legacy records remain untrusted")
        add_identity(migrate)
        migrate.add_argument("--migration-id", required=True)
        migrate.add_argument("--migration-operation-id", required=True)
        migrate.add_argument("--expected-head")
        migrate.set_defaults(handler=handler)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (CliInputError, MigrationError, OperationError, ProviderSyncError, json.JSONDecodeError) as exc:
        _emit(False, "INPUT_INVALID", errors=[str(exc)])
        return 2
    except (FileNotFoundError, OSError) as exc:
        _emit(False, "ENVIRONMENT_UNAVAILABLE", errors=[str(exc)])
        return 3
    except AuthorityError as exc:
        message = str(exc)
        environment_markers = ("no pinned checkout mapping", "git is unavailable", "mapped checkout is not", "cannot read delivery blob")
        code = "ENVIRONMENT_UNAVAILABLE" if any(marker in message for marker in environment_markers) else "POLICY_BLOCKED"
        _emit(False, code, errors=[message])
        return 3 if code == "ENVIRONMENT_UNAVAILABLE" else 1
    except (ReducerError, ServiceError, RecoveryRequired, RevisionConflict, TransactionError, ValueError) as exc:
        _emit(False, "POLICY_BLOCKED", errors=[str(exc)])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
