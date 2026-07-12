#!/usr/bin/env python3
"""Validate fallback or exported Spec structure and task dependencies."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

from _delivery_common import InputError, emit, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    schema = Path(__file__).resolve().parents[1] / "assets" / "spec-structure.schema.json"
    try:
        data, schema_errors = validate_file(args.spec, schema)
        if schema_errors:
            raise InputError("; ".join(schema_errors))
    except InputError as exc:
        emit(False, [str(exc)], {"summary": "input/schema error"}, args.json)
        return 2
    errors: list[str] = []
    criterion_ids = [item["criterion_id"] for item in data["acceptance_criteria"]]
    test_ids = [item["test_id"] for item in data["acceptance_criteria"]]
    task_ids = [item["task_id"] for item in data["tasks"]]
    if len(criterion_ids) != len(set(criterion_ids)):
        errors.append("duplicate acceptance criterion IDs")
    if len(test_ids) != len(set(test_ids)):
        errors.append("duplicate TEST IDs")
    if len(task_ids) != len(set(task_ids)):
        errors.append("duplicate TASK IDs")
    graph: dict[str, list[str]] = defaultdict(list)
    indegree = {task_id: 0 for task_id in task_ids}
    for task in data["tasks"]:
        for dependency in task["depends_on"]:
            if dependency not in indegree:
                errors.append(f"unknown task dependency: {dependency}")
            else:
                graph[dependency].append(task["task_id"])
                indegree[task["task_id"]] += 1
    queue = deque(task_id for task_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        visited += 1
        for child in graph[queue.popleft()]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(task_ids):
        errors.append("task dependency graph contains a cycle")
    emit(not errors, errors, {"summary": f"validated Spec {data['spec_id']}"}, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
