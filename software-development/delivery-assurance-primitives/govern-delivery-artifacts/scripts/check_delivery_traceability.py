#!/usr/bin/env python3
"""Check traceability references and required directed paths."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

from _delivery_common import InputError, approval_match_errors, artifact_index, emit, load_json, validate_file


TRACEABLE_START_TYPES = {
    "source", "requirement", "nfr", "invariant", "change", "discovery",
    "current-behavior", "target-behavior", "unchanged-behavior",
}


def includes_completion_stages(via_types: list[str], end_type: str) -> bool:
    """Require the ordered delivery stages while allowing a Spec or Contract boundary."""
    position = -1
    for alternatives in ({"spec", "contract"}, {"task"}, {"implementation"}, {"test"}, {"evidence"}):
        try:
            position = next(index for index in range(position + 1, len(via_types)) if via_types[index] in alternatives)
        except StopIteration:
            return False
    return end_type == "audit"


def exemption_errors(node: dict, approval_data: dict | None, registry: dict | None) -> list[str]:
    approval_id = node.get("exemption_approval")
    if not approval_id:
        return [f"mandatory traceability start lacks a required path or exemption: {node['id']}"]
    if approval_data is None or registry is None:
        return [f"exemption for {node['id']} requires governed approvals and artifact registry"]
    record = registry.get((node["id"], node["version"]))
    if record is None:
        return [f"exempted node does not resolve to artifact registry: {node['id']}@{node['version']}"]
    approvals = {item["approval_id"]: item for item in approval_data["approvals"]}
    return approval_match_errors(
        approvals.get(approval_id),
        approval_id=approval_id,
        object_id=node["id"],
        object_version=node["version"],
        content_hash=record["content_hash"],
        decisions={"RISK_ACCEPTED"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traceability", type=Path)
    parser.add_argument("--approvals", type=Path, help="Approval registry used to validate exemptions")
    parser.add_argument("--registry", type=Path, help="Artifact registry used to bind exemptions to content hashes")
    parser.add_argument("--suite", choices=["greenfield", "brownfield"], help="Delivery Suite; inferred from sibling delivery.json when available")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    schema = Path(__file__).resolve().parents[1] / "assets" / "traceability.schema.json"
    try:
        data, schema_errors = validate_file(args.traceability, schema)
        if schema_errors:
            raise InputError("; ".join(schema_errors))
        delivery_dir = args.traceability.resolve().parent
        delivery_meta_path = delivery_dir / "delivery.json"
        suite = args.suite
        if delivery_meta_path.is_file():
            inferred = load_json(delivery_meta_path).get("suite")
            if suite and suite != inferred:
                raise InputError("--suite conflicts with sibling delivery.json")
            suite = inferred
        approval_path = args.approvals or ((delivery_dir / "approvals.json") if (delivery_dir / "approvals.json").is_file() else None)
        registry_path = args.registry or ((delivery_dir / "artifact-registry.json") if (delivery_dir / "artifact-registry.json").is_file() else None)
        approval_data = None
        registry = None
        if approval_path:
            approval_data, approval_errors = validate_file(approval_path, Path(__file__).resolve().parents[1] / "assets" / "approval.schema.json")
            if approval_errors:
                raise InputError("; ".join(approval_errors))
        if registry_path:
            registry_data, registry_errors = validate_file(registry_path, Path(__file__).resolve().parents[1] / "assets" / "artifact-registry.schema.json")
            if registry_errors:
                raise InputError("; ".join(registry_errors))
            registry = artifact_index(registry_data)
    except InputError as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    errors: list[str] = []
    nodes = {item["id"]: item for item in data["nodes"]}
    if len(nodes) != len(data["nodes"]):
        errors.append("duplicate node IDs")
    graph: dict[str, list[str]] = defaultdict(list)
    edge_keys: set[tuple[str, str, str]] = set()
    for edge in data["edges"]:
        edge_key = (edge["from"], edge["to"], edge["relation"])
        if edge_key in edge_keys:
            errors.append(f"duplicate traceability edge: {edge['from']} -> {edge['to']} ({edge['relation']})")
        edge_keys.add(edge_key)
        if edge["from"] not in nodes or edge["to"] not in nodes:
            errors.append(f"edge references unknown node: {edge['from']} -> {edge['to']}")
        else:
            graph[edge["from"]].append(edge["to"])
            if edge["source_version"] != nodes[edge["from"]]["version"]:
                errors.append(f"edge source_version does not match node version: {edge['from']}")
    declared_starts = {item["start"] for item in data["required_paths"]}
    if suite:
        for node in nodes.values():
            if node["type"] in TRACEABLE_START_TYPES and node["id"] not in declared_starts:
                errors.extend(exemption_errors(node, approval_data, registry))
    for requirement in data["required_paths"]:
        start = requirement["start"]
        if start not in nodes:
            errors.append(f"required path starts at unknown node {start}")
            continue
        expected = requirement["via_types"] + [requirement["end_type"]]
        if not includes_completion_stages(requirement["via_types"], requirement["end_type"]):
            errors.append(f"required path for {start} omits an ordered Spec/Contract → Task → implementation → test → evidence → audit closure")
        queue, seen, found = deque([(start, 0)]), {(start, 0)}, False
        while queue:
            current, index = queue.popleft()
            if index == len(expected):
                found = True
                break
            for target in graph[current]:
                if nodes[target]["type"] != expected[index]:
                    continue
                state = (target, index + 1)
                if state not in seen:
                    seen.add(state); queue.append(state)
        exemption = nodes[start].get("exemption_approval")
        if not found and exemption:
            errors.extend(exemption_errors(nodes[start], approval_data, registry))
        elif not found:
            route = " -> ".join(expected)
            errors.append(f"no required path from {start} through {route}")
    emit(not errors, errors, {"summary": f"checked {len(data['required_paths'])} required paths"}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
