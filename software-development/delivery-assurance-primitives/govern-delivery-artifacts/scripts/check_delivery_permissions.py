#!/usr/bin/env python3
"""Check a proposed write manifest against role and scope rules."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re

from _delivery_common import InputError, approval_match_errors, artifact_index, emit, load_json, validate_file


ROLE_TYPES = {
    "orchestrator": {"task-package", "gate", "state", "run"},
    "fact-extractor": {"baseline", "discovery", "registry"},
    "spec-author": {"spec", "task", "traceability", "context-package"},
    "contract-owner": {"contract", "contract-test", "registry"},
    "implementer": {"implementation", "test", "evidence"},
    "verifier": {"audit", "evidence", "run"},
    "release-controller": {"release-state", "environment", "evidence", "run"},
    "human-approver": {"approval"},
}


def normalize_relative(path: str) -> str | None:
    if not isinstance(path, str):
        return None
    raw = path.replace("\\", "/")
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or re.match(r"^[A-Za-z]:", raw):
        return None
    if any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def within(path: str, scopes: list[str]) -> bool:
    normalized = normalize_relative(path)
    normalized_scopes = [normalize_relative(scope) for scope in scopes]
    if normalized is None or any(scope is None for scope in normalized_scopes):
        return False
    return any(normalized == scope or normalized.startswith(scope + "/") for scope in normalized_scopes)


def authorization_errors(
    authorization: object,
    path: str,
    approvals: dict[str, dict] | None,
    registry: dict[tuple[str, str], dict] | None,
) -> list[str]:
    if not isinstance(authorization, dict):
        return ["production/environment write lacks structured authorization"]
    required = {"approval_id", "object_id", "object_version", "environment", "scope", "content_hash", "expires_at"}
    missing = sorted(required - set(authorization))
    if missing:
        return ["authorization missing fields: " + ", ".join(missing)]
    if not isinstance(authorization["scope"], list) or not within(path, authorization["scope"]):
        return ["environment write is outside authorization scope"]
    try:
        expires = datetime.fromisoformat(str(authorization["expires_at"]).replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            return ["authorization is expired or lacks timezone"]
    except ValueError:
        return ["authorization expires_at is invalid"]
    if authorization["environment"] not in path.replace("\\", "/").split("/"):
        return ["authorization environment does not match write path"]
    if not isinstance(authorization["content_hash"], str) or len(authorization["content_hash"]) < 8:
        return ["authorization content_hash is invalid"]
    if approvals is None or registry is None:
        return ["environment write requires --approvals and --registry governance inputs"]
    identity = (authorization["object_id"], authorization["object_version"])
    record = registry.get(identity)
    if record is None:
        return [f"authorized object is absent from artifact registry: {identity[0]}@{identity[1]}"]
    if record["content_hash"] != authorization["content_hash"]:
        return ["authorization content_hash does not match artifact registry"]
    return approval_match_errors(
        approvals.get(authorization["approval_id"]),
        approval_id=authorization["approval_id"],
        object_id=authorization["object_id"],
        object_version=authorization["object_version"],
        content_hash=authorization["content_hash"],
        decisions={"APPROVED"},
        required_scope=set(authorization["scope"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--approvals", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = load_json(args.manifest)
        role, writes, scopes = data["role"], data["writes"], data["allowed_paths"]
        if role not in ROLE_TYPES or not isinstance(writes, list) or not isinstance(scopes, list):
            raise InputError("manifest requires a known role, writes array, and allowed_paths array")
        approvals = None
        registry = None
        if args.approvals or args.registry:
            if not args.approvals or not args.registry:
                raise InputError("--approvals and --registry must be provided together")
            assets = Path(__file__).resolve().parents[1] / "assets"
            approval_data, approval_errors = validate_file(args.approvals, assets / "approval.schema.json")
            registry_data, registry_errors = validate_file(args.registry, assets / "artifact-registry.schema.json")
            if approval_errors or registry_errors:
                raise InputError("; ".join(approval_errors + registry_errors))
            approvals = {item["approval_id"]: item for item in approval_data["approvals"]}
            registry = artifact_index(registry_data)
    except (InputError, KeyError, TypeError) as exc:
        emit(False, [str(exc)], {"summary": "input error"}, args.json)
        return 2
    errors: list[str] = []
    if role == "implementer" and not data.get("task_approved", False):
        errors.append("implementation task is not approved")
    for write in writes:
        try:
            artifact_type, path = write["artifact_type"], write["path"]
        except (KeyError, TypeError):
            errors.append("each write requires artifact_type and path")
            continue
        if artifact_type not in ROLE_TYPES[role]:
            errors.append(f"role {role} may not write artifact type {artifact_type}")
        if not within(path, scopes):
            errors.append(f"path outside approved scope: {path}")
        if write.get("parent_kind") == "brownfield" and write.get("actor_run_kind") == "greenfield" and artifact_type == "state":
            errors.append("greenfield child may not change brownfield parent state")
        if artifact_type == "environment":
            errors.extend(authorization_errors(data.get("authorization"), path, approvals, registry))
    emit(not errors, errors, {"summary": f"checked {len(writes)} proposed writes"}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
