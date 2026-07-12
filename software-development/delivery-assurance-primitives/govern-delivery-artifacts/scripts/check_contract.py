#!/usr/bin/env python3
"""Validate a versioned interface contract and its approval reference."""

from __future__ import annotations

import argparse
from pathlib import Path

from _delivery_common import InputError, approval_match_errors, artifact_index, emit, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--approvals", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    schema = Path(__file__).resolve().parents[1] / "assets" / "contract.schema.json"
    try:
        data, schema_errors = validate_file(args.contract, schema)
        if schema_errors:
            raise InputError("; ".join(schema_errors))
        approval_data, approval_errors = validate_file(args.approvals, Path(__file__).resolve().parents[1] / "assets" / "approval.schema.json")
        registry, registry_errors = validate_file(args.registry, Path(__file__).resolve().parents[1] / "assets" / "artifact-registry.schema.json")
        if approval_errors or registry_errors:
            raise InputError("; ".join(approval_errors + registry_errors))
    except InputError as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    record = artifact_index(registry).get((data["contract_id"], data["version"]))
    errors: list[str] = []
    if record is None or record.get("artifact_type") != "contract":
        errors.append("contract identity does not resolve to a contract in the artifact registry")
    else:
        approvals = {item["approval_id"]: item for item in approval_data["approvals"]}
        errors.extend(approval_match_errors(
            approvals.get(data["approval_id"]),
            approval_id=data["approval_id"],
            object_id=data["contract_id"],
            object_version=data["version"],
            content_hash=record["content_hash"],
            decisions={"APPROVED"},
            required_scope=set(data["consumers"]),
        ))
    emit(not errors, errors, {"summary": f"validated contract {data['contract_id']}@{data['version']}"}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
