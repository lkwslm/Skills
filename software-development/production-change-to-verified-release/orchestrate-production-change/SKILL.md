---
name: orchestrate-production-change
description: 编排从生产变更意图到现状发现、影响分析、Delta Spec、受限实施、独立验证和授权发布的 Brownfield 状态机。用于修改已有生产系统、恢复中断变更或管理混合流程时。
---

# 生产变更总控

## 核心边界

只编排 Brownfield 交付、门禁和父 `CR-*` 状态；不得写业务实现、批准自己的产物或未经授权改变外部状态。混合流程中是发布、迁移和最终状态的唯一 owner。

## 启动读取

读取项目指令、仓库与目标 commit、变更意图、环境约束、`.delivery/`、Spec 工件、[工件协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/artifact-protocol.md)、[状态机](../../delivery-assurance-primitives/govern-delivery-artifacts/references/state-machines.md)和[权限模型](../../delivery-assurance-primitives/govern-delivery-artifacts/references/permission-model.md)。恢复时先检查陈旧。

## 前置门禁

- 运行 `$govern-delivery-artifacts` 和 `$integrate-spec-toolchain`，确认权威写入方唯一。
- 登记风险等级、变更窗口、可用运行证据和实际 capability；强隔离不可满足时 fail closed。
- 安装、升级、迁移工具、生产写入和凭证访问均需单独授权。

## 执行流程

1. 委派 `$discover-current-system-behavior` 建立现状与 `DISC-*`。
2. 委派 `$analyze-production-change-impact` 建立 blast radius、回归范围和风险。
3. 委派 `$write-production-delta-spec`，等待对象/version/hash 明确的审批。
4. 一次发放一个批准任务给 `$implement-bounded-production-change`，记录 claim/attempt。
5. 交不同 agent 使用 `$verify-production-change`；只以原始证据推进到 `implementation_accepted`。
6. 委派 `$control-production-release` 检查或在明确授权下执行发布。
7. 按 `captured → baselined → planned → executing → implementation_accepted → release_ready → releasing → released → production_validated → closed` 推进。

## 写入权限

只写父 CR、任务包、风险、门禁、状态和 handoff；不得写实现、Spec、审批、验证结论或绕过发布控制器直接发布。

## 输出与状态

输出工具映射、角色任务、验证范围、发布准备度、停止/恢复条件和最终报告。无生产授权时终态必须停在 `release_ready`。

## 失败、阻塞与陈旧

事实冲突、证据不足、缺审批或授权时 `blocked`；可复现回归为 `failed`。上游变化传播 `stale` 并缩小复验范围，不删除历史。

## Handoff 与完成证据

handoff 列出 CR、commit/artifact hashes、风险、已过门禁、下一 actor、环境/范围/时限授权和未验证项。Greenfield child 只能提供父门禁输入。
