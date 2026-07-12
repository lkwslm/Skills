#!/usr/bin/env python3
"""Compute stale downstream closure from changed artifact hashes."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import tempfile

from _delivery_common import InputError, emit, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--changed", action="append", default=[], metavar="ID[@VERSION]=HASH")
    parser.add_argument("--traceability", type=Path)
    parser.add_argument("--write", action="store_true", help="Persist stale status in the registry")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    schema = Path(__file__).resolve().parents[1] / "assets" / "artifact-registry.schema.json"
    try:
        data, schema_errors = validate_file(args.registry, schema)
        if schema_errors:
            raise InputError("; ".join(schema_errors))
        changes = dict(item.split("=", 1) for item in args.changed if "=" in item)
        if len(changes) != len(args.changed):
            raise InputError("--changed values must use ID=HASH")
    except (InputError, ValueError) as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    records: dict[tuple[str, str], dict] = {}
    latest: dict[str, tuple[str, str]] = {}
    downstream: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for item in data["artifacts"]:
        key = (item["artifact_id"], item["version"])
        records[key] = item
        latest[item["artifact_id"]] = key
        for source in item["derived_from"]:
            downstream[(source["artifact_id"], source["version"])].add(key)
    if args.traceability:
        trace, trace_errors = validate_file(args.traceability, Path(__file__).resolve().parents[1] / "assets" / "traceability.schema.json")
        if trace_errors:
            emit(False, trace_errors, {"summary": "input/schema error"}, args.json)
            return 2
        node_keys = {node["id"]: (node["id"], node["version"]) for node in trace["nodes"]}
        for edge in trace["edges"]:
            if edge["from"] in node_keys and edge["to"] in node_keys:
                downstream[node_keys[edge["from"]]].add(node_keys[edge["to"]])
    changed: set[tuple[str, str]] = set()
    for reference, new_hash in changes.items():
        if "@" in reference:
            artifact_id, version = reference.rsplit("@", 1)
            key = (artifact_id, version)
        else:
            key = latest.get(reference, (reference, ""))
        if key not in records or records[key]["content_hash"] != new_hash:
            changed.add(key)
    stale: set[tuple[str, str]] = set()
    queue = deque(changed)
    while queue:
        for child in downstream[queue.popleft()]:
            if child not in stale:
                stale.add(child); queue.append(child)
    writable_stale = {key for key in stale if key in records}
    if args.write and writable_stale:
        for key in writable_stale:
            records[key]["status"] = "stale"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.registry.parent, delete=False) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(args.registry)
    stale_ids = sorted({artifact_id for artifact_id, _ in writable_stale})
    leaves = sorted({artifact_id for artifact_id, version in writable_stale if not (downstream[(artifact_id, version)] & writable_stale)})
    payload = {"summary": f"{len(writable_stale)} downstream artifacts are stale", "changed": sorted(f"{item}@{version}" for item, version in changed), "stale": stale_ids, "minimum_revalidation": leaves, "written": args.write}
    emit(True, [], payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
