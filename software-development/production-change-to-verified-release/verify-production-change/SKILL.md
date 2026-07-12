---
name: verify-production-change
description: 独立验证生产变更的新增、修改和保持不变条款，检查回归、兼容、迁移、权限、观测和实际 diff 范围。用于决定变更是否达到 implementation_accepted 和 release_ready 时。
---

# 验证生产变更

## 核心边界

验证者必须独立于实现者，从当前基线、批准 Delta Spec 和已发布契约推导预期。不得修实现、改 Spec、批准发布或把实现者叙述当证据。

## 启动读取

读取行为基线、影响图、Delta Spec、保持不变清单、契约、迁移/观测计划、diff、原始 evidence、[追溯 schema](../../delivery-assurance-primitives/govern-delivery-artifacts/assets/traceability.schema.json)和权限模型。

## 前置门禁

角色隔离成立；目标 commit、输入、审批和 evidence 当前；环境足以重放关键验证。否则 `BLOCKED`。

## 执行流程

1. 独立推导新增、修改和保持不变条款的期望。
2. 运行追溯、陈旧、权限和 evidence 门禁，核对实际 diff 范围。
3. 新建 attempt 重跑目标测试、回归、消费者契约、安全权限、迁移 rehearsal 和适用 NFR。
4. 检查 feature flag 默认值、兼容窗口、观测指标、停止阈值和恢复/roll-forward 可执行性。
5. 对每条输出 `PASS/FAIL/BLOCKED`，附期望、实际、命令、原始证据和退回阶段。
6. 只有全部强制条款通过或有合法豁免，才建议 task `accepted`；发布材料完整后才建议变更 `implementation_accepted`/`release_ready`。

## 写入权限

只写验证 attempt、原始日志索引和审计报告；不得写实现、Spec、审批或发布状态。

## 输出与状态

输出条款级审计、兼容/回归/迁移结论、越界 diff、证据缺口和状态建议。

## 失败、阻塞与陈旧

可复现不符合为 `FAIL`；证据/环境/审批不足为 `BLOCKED`。输入变化使审计 `stale` 并要求新 attempt。

## Handoff 与完成证据

向发布控制者提供签名产物 hash、批准 Delta Spec hash、审计 attempt、门禁结果、观察指标、停止/恢复条件和未验证项。
