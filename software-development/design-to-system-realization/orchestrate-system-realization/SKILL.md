---
name: orchestrate-system-realization
description: 编排从已批准系统设计到分层上下文、冻结契约、垂直切片实施和独立系统验收的 Greenfield 交付状态机。用于依据完整设计创建新系统、恢复中断的新系统交付、协调多个专职角色或执行系统级完成门禁时。
---

# 新系统实现总控

## 核心边界

只编排角色、门禁和 Greenfield Delivery 状态；不得编写业务实现、批准自己的输出、直接发布或修改 Brownfield 父变更状态。将 `.delivery/` 工件而非聊天历史作为恢复依据。

## 启动读取

读取项目指令、仓库状态、设计入口、`.delivery/`、现有 Spec 工件、[工件协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/artifact-protocol.md)、[状态机](../../delivery-assurance-primitives/govern-delivery-artifacts/references/state-machines.md)和[权限模型](../../delivery-assurance-primitives/govern-delivery-artifacts/references/permission-model.md)。恢复时先运行陈旧检查。

## 前置门禁

- 运行 `$govern-delivery-artifacts` 验证治理工件；缺失时只初始化 sidecar。
- 运行 `$integrate-spec-toolchain`；复用原生 spec、design/plan 和 tasks，不创建等价副本。
- 确认总控、事实提取、Spec、实现、验证角色可隔离；关键权限无法限制时 fail closed。
- 混合流程中确认 Brownfield 总控是父 `CR-*` 和发布状态的唯一写入方。

## 执行流程

1. 委派 `$establish-system-design-baseline`，阻断高影响开放问题。
2. 委派 `$partition-system-contexts` 生成 L0/L1、ownership 和依赖图。
3. 委派 `$freeze-system-contracts`，在当前 integration epoch 冻结跨域契约。
4. 委派 `$write-system-slice-spec` 生成端到端切片、任务图和 L2 包。
5. 按依赖一次发放一个已批准且未陈旧的任务给 `$implement-system-slice`；记录 claim/attempt。
6. 交由不同 agent 使用 `$verify-system-realization`，仅传权威输入、diff 与原始证据。
7. 只依据机器门禁、独立审计和批准记录推进 `captured → baselined → planned → executing → verified → closed`。

## 写入权限

只写 Greenfield run 的任务包、门禁结果、状态转换和阻塞记录。不得写业务代码、Spec 正文、契约正文、审批或父 Brownfield 状态。

## 输出与状态

输出 run、工具映射、角色任务、门禁、stale 闭包和系统完成报告。只有追溯、关键旅程、跨域契约、不变量、适用 NFR、部署与恢复验证全部通过，才进入 `verified`。

## 失败、阻塞与陈旧

缺决策、审批、环境、隔离或证据时进入 `blocked`；可复现不符合进入 `failed` 并退回产出阶段。上游 hash 变化时传播 `stale`、保留历史证据并计算最小复验范围。

## Handoff 与完成证据

列出对象 ID、状态、权威版本/hash、下一角色、允许读写范围、门禁和证据引用。混合流程只向父变更报告 Greenfield `verified`，不得关闭父 `CR-*`。
