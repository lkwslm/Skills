---
name: verify-system-realization
description: 独立验证新系统需求、契约、实现、测试、跨领域集成、关键旅程和系统级 NFR，并输出条款级结论。用于验收 Greenfield 切片或判断整个系统是否达到 verified 时。
---

# 验证系统实现

## 核心边界

由未实施该任务的角色独立推导预期。不得把实现者结论当证据，不得在验证中修代码、改 Spec、改契约或批准发布。

## 启动读取

读取原始设计定位、基线、L0/L1/L2、批准 Spec、frozen contracts、diff、原始运行结果、共享唯一 schema 源 [`events.py`](../../delivery-assurance-primitives/govern-delivery-artifacts/scripts/delivery_core/events.py) 和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

验证者与实现者隔离；输入、审批和 evidence hash 当前；环境可重放。否则输出 `BLOCKED`，不得降级独立性。

## 执行流程

1. 沿来源独立推导每个条款与 `TEST-*` 的期望。
2. 运行追溯、陈旧、权限和 evidence 检查，确认需求到审计的双向闭包。
3. 审查实际 diff 与任务授权，识别越界及反向修改预言。
4. 新建 attempt 重跑契约、跨域集成、关键 E2E 和适用 NFR。
5. 验证不变量、权限、数据完整性、部署、初始化、迁移和恢复路径。
6. 对每条输出 `PASS`、`FAIL` 或 `BLOCKED`，附期望、实际、原始证据和退回阶段。

## 写入权限

只写验证 attempt、原始日志索引和审计报告；不得写实现、Spec、契约、审批或生产状态。

## 输出与状态

切片全部强制条款通过或有合法豁免时才建议 `verifying → accepted`。系统只有全局完成门禁通过才建议 Delivery `verified`。

## 失败、阻塞与陈旧

可复现不符合为 `FAIL`；证据、环境或审批不足为 `BLOCKED`。上游变化使旧结论 `stale`，必须产生新 attempt。

## Handoff 与完成证据

报告条款级结果、重放命令、退出码、计数、日志 hash、未验证项、追溯缺口和建议状态；不得用汇总 PASS 隐藏局部失败。
