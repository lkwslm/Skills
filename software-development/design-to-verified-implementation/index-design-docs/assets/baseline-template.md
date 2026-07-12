# 设计基线

## Manifest

| 来源 | Hash | 标题/范围 | 状态 |
|---|---|---|---|
| `path` | `sha256` |  | current |

## 术语

| ID | 术语 | 唯一定义 | 来源 |
|---|---|---|---|
| TERM-001 |  |  | `path#heading` |

## 原子需求

| ID | 类型 | 规范化陈述 | 强度 | 来源 | 状态 |
|---|---|---|---|---|---|
| REQ-001 | 功能 |  | must | `path#heading` | captured |

## 开放问题

| ID | 问题/冲突 | 来源 | 候选解释 | 影响 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| OPEN-001 |  |  |  | high |  | open |

## 覆盖复查

将原文覆盖记录写入 `source-coverage.csv`，列为：

`source_path,source_heading,line_start,line_end,classification,mapped_ids,coverage_status,notes`

记录未映射的规范性段落；若为零，写明检查范围和方法。

另建 `traceability.csv`，列为：

`requirement_id,source_refs,spec_id,task_ids,test_ids,implementation_refs,evidence_refs,status`

这两个 CSV 用途不同，不得合并或互相替代。
