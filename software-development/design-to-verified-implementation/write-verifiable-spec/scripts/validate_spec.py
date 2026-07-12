#!/usr/bin/env python3
"""对 SPEC Markdown 执行最低限度的确定性结构检查。"""

from pathlib import Path
import re
import sys

REQUIRED = [
    "## 元数据", "## 目标", "## 非目标", "## 前置条件与依赖",
    "## 接口与数据契约", "## 行为与验收标准", "## 边界与失败路径",
    "## 不变量", "## 非功能维度", "## 实施任务", "## 审批",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: validate_spec.py <SPEC.md>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    errors = [f"缺少章节: {heading}" for heading in REQUIRED if heading not in text]
    for label, pattern in {
        "SPEC ID": r"^# SPEC-[A-Za-z0-9_-]+",
        "来源需求": r"来源需求：.*(?:REQ|NFR|INV|DEC)-",
        "TEST ID": r"^### TEST-[A-Za-z0-9_-]+",
        "TASK ID": r"^### TASK-[A-Za-z0-9_-]+",
        "设计基线 hash": r"设计基线 hash：\s*\S+",
    }.items():
        if not re.search(pattern, text, re.MULTILINE):
            errors.append(f"缺少或为空: {label}")
    if errors:
        print("\n".join(f"ERROR: {e}" for e in errors))
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
