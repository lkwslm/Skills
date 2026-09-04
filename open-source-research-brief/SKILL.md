---
name: open-source-research-brief
description: 通过逐题对齐建立开源项目调研 brief，并在用户正式授权后生成 confirmed 1.0 的 Markdown 需求基准。
---

# 开源项目调研输入对齐

为后续候选发现、初筛和深度调研建立一份用户可读、可修改的 `research-brief.md`。它是所有下游 subagent 的唯一需求输入契约。

## 过程

1. 先按 `grill-with-docs` 的语义进行逐题访谈：使用 grilling 澄清决策，使用 domain-modeling 固定术语。一次只问一个决策问题，并给出推荐答案。
2. 逐项确认目标问题、必须能力、硬约束、可接受缺口、解决思路与使用偏好、部署和数据边界、许可证边界，以及候选发现偏好。
3. 若用户不知道候选项目，确认发现方式、Stars 和维护活跃度等排序偏好；把排序偏好与硬约束分开记录。候选上限默认 20，深度调研上限默认 10。
4. 将已确认内容写入用户指定主题目录下的 `research-brief.md`。详细章节使用 [references/brief-template.md](references/brief-template.md)。
5. 只有用户明确允许正式调查后，才把 front matter 更新为 `status: confirmed`、`version: "1.0"`，并把 brief 交给下游阶段。

## 边界

- 未确认的决策放入“待确认事项”，不写成确定事实。
- 不在 brief 阶段发现、筛选或研究项目。
- brief 确认后，下游 subagent 只读它；任何研究发现写入各自产物。
- 用户明确指定仓库时，把项目身份和仓库地址写入 brief，后续跳过候选发现和初筛。

## 完成标准

只有当 brief 已包含全部必需输入、关键歧义已处理，并且用户明确授权正式调查时，才算完成；此时文件必须是可读的 Markdown，且 front matter 为 `confirmed 1.0`。
