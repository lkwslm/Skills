---
name: orchestrate-spec-delivery
description: 编排从长篇系统设计文档到需求基线、可验证规格、逐任务实现和独立验收的多 agent 交付闭环。用于用户要求依据既有设计生成 spec、按 spec 开发、降低实现偏差、组织多个 agent、建立阶段门禁或恢复中断的规格驱动项目时。
---

# 规格交付总控

## 核心原则

将版本化工件而非聊天上下文作为事实来源。不得承诺“绝对无偏差”；要把偏差变成可追溯、可检测、可阻断的问题。

只负责编排、门禁和状态迁移，不代替专职角色产出或审批自己的工作。

## 启动流程

1. 读取项目指令、仓库状态、设计文档入口和已有 `.specflow/`。
2. 若 `.specflow/` 不存在，从 [project-layout.md](references/project-layout.md) 选择最小目录并创建。
3. 调用 `$index-design-docs` 建立或更新设计基线。长文档不得直接进入编码。
4. 阻断所有高影响冲突、歧义和缺失决策；让用户或有授权的负责人裁决。
5. 调用 `$write-verifiable-spec` 生成或修订 spec、任务和追溯关系。
6. 要求人工明确批准 spec 基线。批准前不得实施。
7. 每次只把一个已批准、依赖满足的任务交给 `$implement-spec-task`。
8. 用与实现者不同的 agent 调用 `$audit-spec-conformance`。只传原始工件、diff 和运行证据，不传实现者的推理结论。
9. 仅在审计通过后标记任务完成并领取下一项；每个垂直切片后运行关键集成或 E2E 检查。

## 角色隔离

- 建账者：提取和定位事实，不写代码。
- Spec 作者：定义可观察行为，不实现或批准自己的 spec。
- 实现者：无权改变 spec、验收条件或设计解释。
- 审计者：独立推导预期，不接受“实现者说已完成”作为证据。
- 用户/负责人：批准需求解释、spec 基线和重大变更。

若环境不能创建独立 agent，暂停在实施或验收门禁，明确说明角色隔离无法满足；不要让同一上下文伪装成独立审计。

## 状态机与门禁

使用以下状态：

`captured → resolved → specified → approved → implementing → verifying → accepted`

任何状态均可进入 `blocked`；设计或 spec 变化使下游进入 `stale`。

- `captured → resolved`：有稳定 ID、原文定位，且无未决高影响问题。
- `resolved → specified`：有可判定验收条件、失败路径、边界和适用 NFR。
- `specified → approved`：追溯完整且由用户/负责人明确批准。
- `approved → implementing`：基线 hash 未变化、任务依赖满足。
- `implementing → verifying`：最小变更完成，附命令、退出码和测试证据。
- `verifying → accepted`：独立审计逐条通过，无未授权变更。

## 失败回路

- 设计含糊或冲突：退回建账阶段，创建开放问题或决策记录。
- Spec 不可实现或不可验证：退回 Spec 作者；禁止实现者自行放宽条件。
- 实现不符：审计者给出失败条款、期望/实际和复现命令，实施者仅修该差异。
- 设计或 spec 改版：标记所有相关实现与证据 `stale`，重新计算影响范围并复验。
- 验证环境缺失或测试不稳定：标记 `blocked`，不得把偶然成功当作通过。

## 工具选择

默认使用仓库内 Markdown/CSV、Git、测试框架和 CI，避免工具锁定。需要现成框架时读取 [tool-landscape.md](references/tool-landscape.md)，按团队环境选择；工具不能替代角色隔离、原文引用和独立验收。

## 完成报告

报告当前基线、已接受/阻塞/陈旧任务、追溯覆盖、独立验证证据和仍需人工决定的事项。没有证据的完成声明一律视为未完成。
