---
name: write-system-slice-spec
description: 把系统基线、领域上下文和冻结契约转化为端到端垂直切片 Spec、任务图、测试和 L2 上下文包。用于为新系统编写或增强可验证切片规格时。
---

# 编写系统切片规格

## 核心边界

按端到端用户价值切片，不按技术层孤立拆分。增强 Spec 工具的权威工件，不复制原生 spec、design 或 tasks；Spec 作者不得实现或批准自己的规格。

## 启动读取

读取 L0、相关 L1、frozen 契约、关键旅程、来源需求、Spec 工具 profile、artifact registry 和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

上下文和来源 hash 必须当前；相关契约在当前 epoch 为 `frozen`；高影响开放问题关闭。否则 `blocked`。

## 执行流程

1. 选择一个可独立观察价值的切片，映射 `REQ/NFR/INV/DEC` 与明确非目标。
2. 在权威 Spec 工具工件中定义正例、反例、边界、失败路径和非法状态。
3. 对安全、性能、容量、恢复和可观测性给出量化判据或不适用理由。
4. 引用契约 ID/version/hash，禁止复制契约正文或引入未冻结语义。
5. 创建 `TEST-*` 与可独立验证的 `TASK-*`，记录依赖、允许/禁止写入和完成命令。
6. 生成具有独立 ID/version/typed digest 的 L2 context package：L0、相关 L1、当前切片、直接依赖和批准写范围；只通过 `deliveryctl commit` 将其登记为 `context-package`，不与 task 复用身份。
7. 更新追溯边并提交不同角色评审；通过后只到 `draft/reviewed`，等待批准。

## 写入权限

只写批准前的权威切片 Spec、tasks、测试定义、L2 manifest 和追溯关系；不得写实现、审批或 accepted 状态。

## 输出与状态

输出原生 Spec/task ID 映射、L2 包、测试与依赖图。仅记录对象和版本明确的审批后，任务才进入 `approved`。

## 失败、阻塞与陈旧

不可判真条款、无来源需求、未冻结依赖或自相矛盾时 `blocked`。上游变化时标记切片、任务和旧审批 `stale`。

## Handoff 与完成证据

向实现者提供一个已批准 task、L2 ID/hash、契约版本、允许写范围、基线命令、目标失败测试和审批引用。
