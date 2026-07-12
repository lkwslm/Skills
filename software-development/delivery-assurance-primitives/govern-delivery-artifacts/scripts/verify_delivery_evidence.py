#!/usr/bin/env python3
"""Validate completion evidence and its non-schema gate rules."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from _delivery_common import InputError, approval_match_errors, artifact_index, emit, load_json, validate_file
from check_delivery_permissions import normalize_relative


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    schema = Path(__file__).resolve().parents[1] / "assets" / "evidence.schema.json"
    assets = Path(__file__).resolve().parents[1] / "assets"
    try:
        data, schema_errors = validate_file(args.evidence, schema)
        if schema_errors:
            raise InputError("; ".join(schema_errors))
        delivery = args.evidence.resolve().parent.parent
        approval_data, approval_errors = validate_file(delivery / "approvals.json", assets / "approval.schema.json")
        registry, registry_errors = validate_file(delivery / "artifact-registry.json", assets / "artifact-registry.schema.json")
        if approval_errors or registry_errors:
            raise InputError("; ".join(approval_errors + registry_errors))
        delivery_meta = load_json(delivery / "delivery.json")
        if not isinstance(delivery_meta, dict):
            raise InputError("delivery.json is not an object")
    except InputError as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    errors: list[str] = []
    started = parse_time(data["started_at"])
    ended = parse_time(data["ended_at"])
    if ended < started:
        errors.append("ended_at precedes started_at")
    approvals = approval_data["approvals"]
    approvals_by_id = {item["approval_id"]: item for item in approvals}
    registry_by_identity = artifact_index(registry)
    if data["skipped"]:
        if len(data["skip_reasons"]) < data["skipped"] or not data["skip_approval_refs"]:
            errors.append("skipped checks lack reasons or approval references")
        allowed_objects = set(data["requirement_ids"]) | set(data["test_ids"])
        for approval_id in data["skip_approval_refs"]:
            approval = approvals_by_id.get(approval_id)
            if approval is None or approval.get("object_id") not in allowed_objects:
                errors.append(f"skip approval is absent or does not target a skipped requirement/test: {approval_id}")
                continue
            record = registry_by_identity.get((approval["object_id"], approval["object_version"]))
            if record is None:
                errors.append(f"skip approval object is absent from artifact registry: {approval['object_id']}@{approval['object_version']}")
                continue
            errors.extend(approval_match_errors(
                approval,
                approval_id=approval_id,
                object_id=record["artifact_id"],
                object_version=record["version"],
                content_hash=record["content_hash"],
                decisions={"RISK_ACCEPTED"},
            ))
    if data["failed"] or data["exit_code"] != 0:
        errors.append("evidence contains failures or non-zero exit code")
    if data["unverified_items"]:
        errors.append("completion evidence contains unverified items; resolve them or govern exemptions before this gate")
    if data["valid_until"] and parse_time(data["valid_until"]) < datetime.now(timezone.utc):
        errors.append("evidence has expired")
    normalized_log = normalize_relative(data["raw_log_path"])
    raw_log = delivery.parent / normalized_log if normalized_log else None
    if raw_log is None:
        errors.append("raw log path is absolute or contains traversal")
    elif not raw_log.is_file():
        errors.append(f"raw log does not exist: {data['raw_log_path']}")
    else:
        actual_log_hash = hashlib.sha256(raw_log.read_bytes()).hexdigest()
        if actual_log_hash != data["raw_log_hash"]:
            errors.append("raw log hash does not match")
    if delivery_meta.get("commit_hash") != data["commit_hash"]:
        errors.append("evidence commit hash does not match delivery target")
    for artifact_id, content_hash in data["artifact_hashes"].items():
        matching = [item for (item_id, _), item in registry_by_identity.items() if item_id == artifact_id and item["content_hash"] == content_hash]
        if len(matching) != 1:
            errors.append(f"artifact hash does not match registry: {artifact_id}")
    emit(not errors, errors, {"summary": f"verified evidence {data['evidence_id']}", "attempt_id": data["attempt_id"]}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
