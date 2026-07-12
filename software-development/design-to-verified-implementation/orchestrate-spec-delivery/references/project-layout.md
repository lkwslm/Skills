# 项目工件协议

## 目录

```text
.specflow/
  manifest.md             # 来源文件、版本/hash、基线时间
  glossary.md             # 术语、实体、状态和权限定义
  requirements.md         # 原子需求、约束、不变量、非目标
  open-questions.md       # 冲突、歧义、假设和裁决
  source-coverage.csv     # 原文段落→需求/术语/问题的覆盖
  traceability.csv        # 需求→spec→任务→测试→实现→证据
  specs/SPEC-*.md
  tasks.md
  changes/CR-*.md
  evidence/TASK-*.md
  audits/TASK-*.md
```

已有仓库约定等价目录时复用，不要复制第二套事实来源。

## ID

- `REQ-*`：功能需求
- `NFR-*`：非功能需求
- `INV-*`：必须始终成立的不变量
- `DEC-*`：已批准决策
- `OPEN-*`：未决问题
- `SPEC-*`：规格切片
- `TASK-*`：可独立实施任务
- `TEST-*`：验证项
- `CR-*`：变更请求

ID 创建后不得复用。删除项保留记录并标为废弃。

## 基线

`manifest.md` 至少记录来源路径、内容 hash、状态和更新时间。摘要只用于导航，关键约束必须回到原文定位。任一来源 hash 变化时，沿追溯矩阵标记下游为 `stale`。

## 追溯列

`requirement_id,source_refs,spec_id,task_ids,test_ids,implementation_refs,evidence_refs,status`

多个值用 `;` 分隔。每条强制需求必须有 spec、任务、测试、实现和证据；未实施阶段可留空，但不得标记 `accepted`。

## 来源覆盖列

`source_path,source_heading,line_start,line_end,classification,mapped_ids,coverage_status,notes`

`source-coverage.csv` 用于证明原文没有遗漏；`traceability.csv` 用于证明需求已交付。不得混用两个 schema。
