#!/usr/bin/env python3
"""检查 traceability.csv 的唯一性、状态和值完整性。"""

import csv
from pathlib import Path
import sys

FIELDS = [
    "requirement_id", "source_refs", "spec_id", "task_ids", "test_ids",
    "implementation_refs", "evidence_refs", "status",
]
VALID_STATES = {"captured", "resolved", "specified", "approved", "implementing", "verifying", "accepted", "blocked", "stale", "deprecated"}


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: check_traceability.py <traceability.csv>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    errors: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            print("ERROR: 缺少列: " + ", ".join(missing))
            return 1
        seen: set[str] = set()
        rows = list(reader)
    for line, row in enumerate(rows, start=2):
        rid = row["requirement_id"].strip()
        if not rid:
            errors.append(f"第 {line} 行缺少 requirement_id")
        elif rid in seen:
            errors.append(f"第 {line} 行 requirement_id 重复: {rid}")
        seen.add(rid)
        if not row["source_refs"].strip():
            errors.append(f"第 {line} 行 {rid} 缺少 source_refs")
        state = row["status"].strip()
        if state not in VALID_STATES:
            errors.append(f"第 {line} 行 {rid} 状态无效: {state}")
        if state in {"approved", "implementing", "verifying", "accepted"}:
            for field in ("spec_id", "task_ids", "test_ids"):
                if not row[field].strip():
                    errors.append(f"第 {line} 行 {rid} 在 {state} 状态缺少 {field}")
        if state == "accepted":
            for field in ("implementation_refs", "evidence_refs"):
                if not row[field].strip():
                    errors.append(f"第 {line} 行 {rid} 已 accepted 但缺少 {field}")
    if not rows:
        errors.append("追溯矩阵为空")
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print(f"OK: {len(rows)} 条需求追溯记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
