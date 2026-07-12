#!/usr/bin/env python3
"""Validate .delivery JSON artifacts and recorded state transitions."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from _delivery_common import EXCEPTIONAL, InputError, artifact_index, emit, load_json, transition_allowed, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Repository root containing .delivery")
    parser.add_argument("--json", action="store_true", help="Write a JSON result to stdout")
    args = parser.parse_args()
    delivery = args.root.resolve() / ".delivery"
    assets = Path(__file__).resolve().parents[1] / "assets"
    required = {
        "artifact-registry.json": "artifact-registry.schema.json",
        "state.json": "delivery-state.schema.json",
        "traceability.json": "traceability.schema.json",
        "approvals.json": "approval.schema.json",
    }
    errors: list[str] = []
    checked: list[str] = []
    meta: dict = {}
    kinds: dict[str, str] = {}
    context_packages: list[dict] = []
    try:
        for name in ("context-packages", "evidence", "audits", "runs"):
            path = delivery / name
            if not path.is_dir():
                errors.append(f"missing required directory {path}")
        delivery_meta = delivery / "delivery.json"
        if not delivery_meta.is_file():
            errors.append(f"missing required artifact {delivery_meta}")
        else:
            meta = load_json(delivery_meta)
            required_meta = {"suite", "run_id", "target", "risk_level", "commit_hash", "spec_tool_profile"}
            missing_meta = sorted(required_meta - set(meta)) if isinstance(meta, dict) else sorted(required_meta)
            if missing_meta:
                raise InputError("delivery.json missing fields: " + ", ".join(missing_meta))
            if meta.get("suite") not in {"greenfield", "brownfield"}:
                raise InputError("delivery.json suite must be greenfield or brownfield")
            profile_ref = meta.get("spec_tool_profile")
            profile_fields = {"artifact_id", "version", "content_hash"}
            if not isinstance(profile_ref, dict) or set(profile_ref) != profile_fields:
                raise InputError("delivery.json spec_tool_profile must contain artifact_id, version, and content_hash")
            checked.append("delivery.json")
        for name, schema in required.items():
            path = delivery / name
            if not path.is_file():
                errors.append(f"missing required artifact {path}")
                continue
            _, schema_errors = validate_file(path, assets / schema)
            if schema_errors:
                raise InputError(f"{name}: " + "; ".join(schema_errors))
            checked.append(name)
        for path in sorted((delivery / "context-packages").glob("*.json")):
            package, schema_errors = validate_file(path, assets / "context-package.schema.json")
            if schema_errors:
                raise InputError(f"{path.name}: " + "; ".join(schema_errors))
            context_packages.append(package)
            checked.append(str(path.relative_to(delivery)))
        for path in sorted((delivery / "evidence").glob("*.json")):
            _, schema_errors = validate_file(path, assets / "evidence.schema.json")
            if schema_errors:
                raise InputError(f"{path.name}: " + "; ".join(schema_errors))
            checked.append(str(path.relative_to(delivery)))
        evidence_ids = set()
        for path in sorted((delivery / "evidence").glob("*.json")):
            evidence_ids.add(load_json(path).get("evidence_id"))
        audit_ids = set()
        for path in sorted((delivery / "audits").glob("*.json")):
            audit = load_json(path)
            required_audit = {"audit_id", "result", "evidence_refs", "verified_by"}
            if not isinstance(audit, dict) or required_audit - set(audit):
                raise InputError(f"{path.name}: invalid audit structure")
            if audit["result"] not in {"PASS", "FAIL", "BLOCKED"}:
                raise InputError(f"{path.name}: invalid audit result")
            missing_evidence = sorted(set(audit["evidence_refs"]) - evidence_ids)
            if missing_evidence:
                errors.append(f"{path.name}: audit references unknown evidence: {', '.join(missing_evidence)}")
            audit_ids.add(audit["audit_id"])
            checked.append(str(path.relative_to(delivery)))
        approvals = load_json(delivery / "approvals.json") if (delivery / "approvals.json").is_file() else {"approvals": []}
        approval_ids = {item["approval_id"] for item in approvals.get("approvals", [])}
        known_gate_refs = evidence_ids | audit_ids | approval_ids
        if (delivery / "state.json").is_file():
            state = load_json(delivery / "state.json")
            if meta.get("suite") != state.get("suite"):
                errors.append("delivery.json and state.json suite values differ")
            objects = state.get("objects", [])
            kinds = {item["object_id"]: item["kind"] for item in objects}
            current_states = {item["object_id"]: item["state"] for item in objects}
            if len(kinds) != len(objects):
                errors.append("duplicate state object IDs")
            by_object: dict[str, list[dict]] = defaultdict(list)
            for item in state.get("transitions", []):
                kind = kinds.get(item["object_id"])
                if not kind:
                    errors.append(f"transition references unknown object {item['object_id']}")
                if not item["evidence_refs"]:
                    errors.append(f"transition for {item['object_id']} has no gate evidence")
                for reference in item["evidence_refs"]:
                    if reference not in known_gate_refs:
                        errors.append(f"transition references unknown gate evidence {reference}")
                by_object[item["object_id"]].append(item)
            initial = {"greenfield": "captured", "brownfield": "captured", "task": "draft", "contract": "draft"}
            for object_id, kind in kinds.items():
                history = by_object.get(object_id, [])
                if not history:
                    errors.append(f"state object {object_id} has no transition history")
                    continue
                if history[0]["old_state"] != initial[kind]:
                    errors.append(f"state history for {object_id} does not start at {initial[kind]}")
                recovery_origin = None
                previous_at = None
                for transition in history:
                    old_state, new_state = transition["old_state"], transition["new_state"]
                    if not transition_allowed(kind, old_state, new_state, recovery_origin):
                        errors.append(f"illegal {kind} transition {old_state} -> {new_state} for {object_id}")
                    expected_gate = "PASS"
                    if new_state in {"blocked", "stale"}:
                        expected_gate = "BLOCKED"
                    elif new_state == "failed":
                        expected_gate = "FAIL"
                    if transition["gate_result"] != expected_gate:
                        errors.append(f"transition {old_state} -> {new_state} for {object_id} requires gate_result {expected_gate}")
                    current_at = datetime.fromisoformat(transition["at"].replace("Z", "+00:00"))
                    if previous_at is not None and current_at < previous_at:
                        errors.append(f"state history timestamps are not ordered for {object_id}")
                    previous_at = current_at
                    if old_state not in EXCEPTIONAL and new_state in EXCEPTIONAL:
                        recovery_origin = old_state
                    elif old_state in EXCEPTIONAL and new_state not in EXCEPTIONAL:
                        recovery_origin = None
                for previous, current in zip(history, history[1:]):
                    if previous["new_state"] != current["old_state"]:
                        errors.append(f"non-contiguous state history for {object_id}")
                if history[-1]["new_state"] != current_states[object_id]:
                    errors.append(f"current state for {object_id} does not match its last transition")
        if (delivery / "artifact-registry.json").is_file():
            registry = load_json(delivery / "artifact-registry.json")
            records: dict[tuple[str, str], dict] = {}
            for item in registry.get("artifacts", []):
                key = (item["artifact_id"], item["version"])
                if key in records:
                    errors.append(f"duplicate artifact identity {key[0]}@{key[1]}")
                records[key] = item
            for item in registry.get("artifacts", []):
                for source in item["derived_from"]:
                    key = (source["artifact_id"], source["version"])
                    upstream = records.get(key)
                    if upstream is None:
                        errors.append(f"{item['artifact_id']} derives from unknown artifact {key[0]}@{key[1]}")
                    elif upstream["content_hash"] != source["content_hash"]:
                        errors.append(f"{item['artifact_id']} records a stale hash for {key[0]}@{key[1]}")
            profile_ref = meta.get("spec_tool_profile")
            if isinstance(profile_ref, dict):
                profile = records.get((profile_ref["artifact_id"], profile_ref["version"]))
                if profile is None or profile.get("artifact_type") != "spec-tool-profile" or profile.get("content_hash") != profile_ref["content_hash"]:
                    errors.append("delivery.json spec_tool_profile does not resolve to the artifact registry")
            package_ids = {package["package_id"] for package in context_packages}
            if len(package_ids) != len(context_packages):
                errors.append("duplicate context package IDs")
            for package in context_packages:
                record = records.get((package["package_id"], package["version"]))
                if record is None or record.get("artifact_type") != "context-package" or record.get("content_hash") != package["content_hash"]:
                    errors.append(f"context package does not resolve to artifact registry: {package['package_id']}@{package['version']}")
                for source in package["sources"]:
                    upstream = records.get((source["artifact_id"], source["version"]))
                    if upstream is None or upstream["content_hash"] != source["content_hash"]:
                        errors.append(f"context package source does not resolve to artifact registry: {package['package_id']} -> {source['artifact_id']}@{source['version']}")
                for dependency in package["dependencies"]:
                    if "@" in dependency:
                        dependency_id, version = dependency.rsplit("@", 1)
                        if (dependency_id, version) not in records:
                            errors.append(f"context package dependency is unknown: {package['package_id']} -> {dependency}")
                    elif dependency not in package_ids:
                        errors.append(f"context package dependency is unknown: {package['package_id']} -> {dependency}")
            if (delivery / "traceability.json").is_file():
                traceability = load_json(delivery / "traceability.json")
                for node in traceability.get("nodes", []):
                    record = records.get((node["id"], node["version"]))
                    if record is None:
                        errors.append(f"traceability node is absent from artifact registry: {node['id']}@{node['version']}")
                    elif record["artifact_type"] != node["type"]:
                        errors.append(f"traceability node type differs from artifact registry: {node['id']}@{node['version']}")
            for evidence_id in evidence_ids:
                if not any(item["artifact_id"] == evidence_id and item["artifact_type"] == "evidence" for item in records.values()):
                    errors.append(f"evidence file is absent from artifact registry: {evidence_id}")
            for audit_id in audit_ids:
                if not any(item["artifact_id"] == audit_id and item["artifact_type"] == "audit" for item in records.values()):
                    errors.append(f"audit file is absent from artifact registry: {audit_id}")
            approval_ids_seen: set[str] = set()
            for approval in approvals.get("approvals", []):
                approval_id = approval["approval_id"]
                if approval_id in approval_ids_seen:
                    errors.append(f"duplicate approval ID {approval_id}")
                approval_ids_seen.add(approval_id)
                record = records.get((approval["object_id"], approval["object_version"]))
                if record is None:
                    errors.append(f"approval object is absent from artifact registry: {approval['object_id']}@{approval['object_version']}")
                elif record["content_hash"] != approval["content_hash"]:
                    errors.append(f"approval content hash differs from artifact registry: {approval_id}")
            for object_id, kind in kinds.items():
                if kind in {"task", "contract", "brownfield"} and not any(item["artifact_id"] == object_id for item in records.values()):
                    errors.append(f"state object is absent from artifact registry: {object_id}")
            if (delivery / "state.json").is_file():
                state = load_json(delivery / "state.json")
                for transition in state.get("transitions", []):
                    for reference in transition["input_versions"]:
                        if "@" not in reference:
                            errors.append(f"state input must use ID@VERSION: {reference}")
                            continue
                        artifact_id, version = reference.rsplit("@", 1)
                        if (artifact_id, version) not in records:
                            errors.append(f"state input is absent from artifact registry: {reference}")
    except InputError as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    emit(not errors, errors, {"summary": f"validated {len(checked)} artifacts", "checked": checked}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
