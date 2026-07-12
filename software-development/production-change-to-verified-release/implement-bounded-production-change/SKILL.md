---
name: implement-bounded-production-change
description: 在已批准 Delta Spec 和修改范围内建立回归与目标失败测试，实施最小、兼容且可恢复的代码、配置或迁移变更。用于执行一个 Brownfield 任务或修复其验证偏差时。
---

# 实施受限生产变更

## 核心边界

一次只领取一个任务，默认保持所有未授权行为。不得无关重构、静默改契约、修改 Spec/审批/预言或直接写生产。

## 启动读取

读取批准的 Delta Spec/task、当前行为基线、影响图、允许写范围、claim/attempt、目标 commit、迁移/flag 条件、[权限模型](../../delivery-assurance-primitives/govern-delivery-artifacts/references/permission-model.md)和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

任务 `approved` 且未领取；依赖满足；全部输入 hash 当前；写范围可限制；基线测试命令可运行。否则 `blocked`。

## 执行流程

1. 记录 claim/attempt，先运行当前行为回归。
2. 为目标变化建立失败测试，并为保持不变条款补足回归/契约测试。
3. 做最小代码、配置、兼容层、迁移或 feature flag 变更；保持默认安全状态。
4. 运行目标测试、影响图规定的回归、契约、迁移 rehearsal 和适用 NFR。
5. 记录 commit/tree hash、工件 hashes、环境、命令、计数、原始日志/hash、未验证项和失效条件。
6. 运行权限、真实 diff 与证据门禁，只推进到 `verifying`。

## 写入权限

只写批准的代码/配置/迁移范围、测试和本 attempt 证据；不得写 Spec、审批、审计、生产状态或超范围环境。

## 输出与状态

输出最小 diff、回归/目标测试、迁移或 flag 实现和 evidence。实现者不能标记 `accepted` 或 `release_ready`。

## 失败、阻塞与陈旧

发现范围外行为变化或契约需求时创建变更请求并停止。测试不符 `failed`；环境/权限缺失 `blocked`；输入变化 `stale`。

## Handoff 与完成证据

向验证者提供原始权威输入、实际 diff、迁移/flag 状态、attempt、日志 hashes、测试计数和所有未验证风险。
