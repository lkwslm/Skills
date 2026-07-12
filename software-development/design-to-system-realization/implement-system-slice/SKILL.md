---
name: implement-system-slice
description: 在已批准且未陈旧的 Greenfield 切片任务下，以受限上下文和最小 diff 实施代码与测试并记录可复核证据。用于按冻结契约实现一个新系统任务或修复该任务的审计偏差时。
---

# 实施系统切片

## 核心边界

一次只领取一个任务，只读 L0、相关 L1、当前 L2 和必要代码。不得改设计基线、Spec、审批、冻结契约、测试预言或任务外业务行为。

## 启动读取

读取 task ID/status、claim/attempt、L2 manifest、frozen contract hashes、审批、允许写范围、验证命令、[权限模型](../../delivery-assurance-primitives/govern-delivery-artifacts/references/permission-model.md)和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

任务必须 `approved` 且未被领取；依赖 accepted；L0/L1/L2 和契约 hash 当前；写范围可强制。任一不满足即 `blocked`。

## 执行流程

1. 记录唯一 claim 与 attempt，复述可观察完成条件和写范围。
2. 运行基线测试；新增行为先建立失败验收/契约测试，缺陷先形成可复现失败。
3. 做满足当前任务的最小实现，不做无关重构。
4. 运行任务测试、契约测试、受影响回归和指定 NFR 检查。
5. 记录真实命令、退出码、计数、环境、commit/tree hash、原始日志路径/hash 和未验证项。
6. 运行权限、真实 diff 与证据检查，只把任务推进到 `verifying`。

## 写入权限

只写批准的业务代码范围、测试、实现引用和本 attempt 证据。不得写 Spec、契约、审批、审计结论或 `accepted`。

## 输出与状态

输出最小 diff、测试和机器可复核 evidence。实现完成只允许 `implementing → verifying`。

## 失败、阻塞与陈旧

上下文缺口先创建扩展请求；写范围、业务范围或契约变化回审批。测试失败为 `failed`，环境缺失为 `blocked`，上游 hash 变化立即停止并标 `stale`。

## Handoff 与完成证据

向独立验证者提供权威输入 URI/hash、diff、原始日志、attempt、测试计数与未验证项；不要传实现者推理作为预期来源。
