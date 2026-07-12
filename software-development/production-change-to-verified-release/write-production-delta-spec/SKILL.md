---
name: write-production-delta-spec
description: 编写生产变更的当前、目标和保持不变行为，以及兼容、迁移、观测、停止、恢复和 roll-forward 条件。用于把已评审影响范围转化为可批准的 Delta Spec 和部署任务时。
---

# 编写生产变更 Delta Spec

## 核心边界

只定义已批准意图的增量，不重写全系统规格，不隐式授权改变现有行为。复用 Spec 工具原生 change/spec 工件，不维护第二份可写 tasks。

## 启动读取

读取当前行为基线、影响图、`DISC/OPEN` 决策、批准意图、风险/发布约束、Spec 工具 profile、artifact registry 和[证据协议](../../delivery-assurance-primitives/govern-delivery-artifacts/references/evidence-protocol.md)。

## 前置门禁

当前行为和影响图必须当前且已评审；高风险未知项有决策；权威 Spec/tasks 写入方唯一。

## 执行流程

1. 分别列出当前行为、目标行为和必须保持不变行为，并映射来源。
2. 定义正反边界、失败处理、权限、审计和兼容性矩阵。
3. 定义数据/配置迁移顺序、可逆点、回滚或不可逆后的 roll-forward/恢复方案。
4. 定义 feature flag/灰度、业务技术指标、阈值、观察窗、停止与恢复条件。
5. 将变化拆成可独立验证、可安全部署的任务，记录允许写范围和验证命令。
6. 为每个任务生成具有独立 ID/version/hash 的 Brownfield context package，登记来源、依赖、允许读写范围和 artifact registry 关系；不得与 task 复用身份。
7. 更新追溯图并交不同角色评审；作者不得批准。

## 写入权限

只写批准前的权威 Delta Spec、原生 tasks、任务 context packages、测试/迁移/观测计划、registry 关系和追溯；不得写实现、审批或发布状态。

## 输出与状态

输出 change/spec ID/version/hash、保持不变清单、兼容矩阵、迁移/恢复、灰度/监控和任务图。明确审批后任务才 `approved`。

## 失败、阻塞与陈旧

缺保持不变条款、迁移恢复、停止条件或不可判真验收时 `blocked`。基线/影响/意图变化时标记 Spec、tasks 和旧审批 `stale`。

## Handoff 与完成证据

提供一个批准 task、Spec hash、写范围、当前行为回归、目标失败测试、迁移/flag 条件和审批引用。
