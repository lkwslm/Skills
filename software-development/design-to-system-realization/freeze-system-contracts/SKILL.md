---
name: freeze-system-contracts
description: 定义并版本化冻结当前 integration epoch 的跨模块接口、事件和共享数据契约，包含 owner、消费者、兼容窗口和契约测试。用于多 agent 并行前建立稳定边界或审批契约变化时。
---

# 冻结系统契约

## 核心边界

冻结当前 epoch 的批准版本，不阻止显式演进。每个契约必须有唯一 owner；不得静默修改消费者语义或批准自己的兼容例外。

## 启动读取

读取 L0、相关 L1、依赖图、不变量、关键旅程、Spec 工具 profile、artifact registry 和[状态机](../../delivery-assurance-primitives/govern-delivery-artifacts/references/state-machines.md)。

## 前置门禁

上下文包必须当前且 ownership 唯一；跨域冲突、未知消费者或未批准设计决策存在时 `blocked`。

## 执行流程

1. 为接口、事件和共享数据定义 schema、版本、错误、幂等、顺序、超时、重试与兼容策略。
2. 登记 owner、消费者、依赖版本、兼容窗口和退役条件。
3. 生成 provider/consumer 契约测试骨架并关联 `TEST-*`。
4. 独立评审后运行共享 `check_contract.py <contract> --approvals <approvals> --registry <registry> --json`，确认审批绑定当前 ID/version/hash 并覆盖全部消费者，再按 `draft → reviewed → frozen` 推进当前 epoch 版本。
5. 变化时创建 Contract Change 和新版本，执行消费者兼容检查并传播 `stale`；不得覆盖 frozen 版本。

## 写入权限

契约 owner 只写自己拥有的契约版本和测试骨架；不得写消费者实现、批准记录或任务完成状态。

## 输出与状态

输出版本化契约、owner、消费者、测试、epoch 和变更规则。所有跨域边界 frozen 后才允许并行实施。

## 失败、阻塞与陈旧

owner 冲突、消费者不明、兼容策略缺失或测试不可判真时 `blocked`。上游变化时将相关契约和任务标为 `stale`。

## Handoff 与完成证据

提供 frozen contract ID/version/hash、epoch、消费者、测试选择器、兼容窗口和审批引用。
