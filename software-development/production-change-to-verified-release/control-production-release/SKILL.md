---
name: control-production-release
description: 在明确人工授权和组织制度约束下检查或执行灰度发布、监控、停止、回滚、恢复和发布后验证；无权限时只生成 handoff。用于已验证 Brownfield 变更的发布准备和受控发布时。
---

# 控制生产发布

## 核心边界

默认只计划和检查。只有授权记录明确对象、环境、范围、动作和时限时才改变外部状态；不得改代码/Spec、扩大范围或临时降低阈值。

## 启动读取

读取 `implementation_accepted` 变更、签名产物及 hash、批准、迁移/灰度/监控/停止/恢复方案、目标环境制度、[权限模型](../../delivery-assurance-primitives/govern-delivery-artifacts/references/permission-model.md)和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

以外部 expected head 运行 `deliveryctl validate`，重新计算 commit/artifact/config digests，并核对审批范围、环境、变更窗口、迁移顺序、可逆点、监控可用性和实际 capability。执行任何环境写入前，解析 signed approval event，绑定 exact 对象 ID/version/digest、run/attempt、环境、路径范围和有效期。无生产授权时只输出 handoff 并停在 `release_ready`。

## 执行流程

1. 先生成可执行 release plan、检查项和人工确认点。
2. 获得明确授权后按批准批次执行，记录每个 attempt 和外部动作。
3. 观察预定义业务/技术指标与窗口；不得在发布中修改阈值。
4. 达停止条件时暂停；达回滚条件时仅在授权范围内回滚。
5. 越过不可逆点后使用批准的 roll-forward/恢复方案，不声称可回滚。
6. 由独立验证确认生产行为后，才建议 `released → production_validated → closed`。

## 写入权限

只在授权范围内写目标环境和发布状态；不得写代码、Spec、审批、扩大环境或替代独立验证。

## 输出与状态

输出准备度、授权、动作日志、指标、停止/恢复决策与生产验证证据。计划模式终态为 `release_ready`。

## 失败、阻塞与陈旧

缺授权、hash 不匹配、监控不可用或窗口失效时 `BLOCKED`。指标越界按批准策略暂停/恢复。任何输入变化使 release plan `stale`。

## Handoff 与完成证据

无权限时提供精确命令/步骤、对象和环境、hash、审批需求、观察窗、阈值及停止/恢复条件；不得伪造 `released` 或 `production_validated`。
