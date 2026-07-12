---
name: partition-system-contexts
description: 从已解决冲突的系统基线划分领域 ownership、依赖图以及 L0/L1 上下文包，并管理可审计的上下文扩展。用于控制长设计上下文、拆分领域职责或为垂直切片准备最小完备上下文时。
---

# 划分系统上下文

## 核心边界

按业务职责和依赖划分上下文，不机械切文档，不重新定义全局术语，不修改设计基线或契约。

## 启动读取

读取已批准且未陈旧的设计基线、术语、不变量、来源覆盖、artifact registry 和[上下文包 schema](../../delivery-assurance-primitives/govern-delivery-artifacts/assets/context-package.schema.json)。

## 前置门禁

基线必须 `resolved`，高影响 `OPEN-*` 已关闭；缺失 ownership 或依赖信息时停止并退回基线阶段。

## 执行流程

1. 生成 L0 系统宪法：目标、非目标、术语、架构原则、安全规则和全局不变量。
2. 划分领域及唯一 owner，生成 L1 包：模型、状态、数据、接口、依赖和适用的 L0 约束。
3. 建立领域依赖图，识别跨域事务、共享数据、全局旅程和循环依赖。
4. 为每个包分配独立 package ID/version/hash，记录来源、依赖闭包、允许读范围和 canonicalization 版本，并以 `context-package` 类型登记到 artifact registry；不得与 task 或其他工件复用 ID。
5. 包不完备时创建上下文扩展请求；只读扩展可按策略批准，写范围或业务范围变化回审批门禁。

## 写入权限

只写 L0/L1 manifests、领域地图、ownership、依赖图、风险和扩展请求；不得写 Spec、契约、tasks 或实现。

## 输出与状态

输出可验证上下文包及 registry 关系。所有需求和不变量均有唯一 owner、消费者依赖闭包完整后，才交给契约阶段。

## 失败、阻塞与陈旧

重复 ownership、未解释的跨域共享或依赖缺口为 `blocked`。基线 hash 变化时将受影响包及下游标为 `stale`。

## Handoff 与完成证据

提供每个包的 ID/version/hash、registry 引用、源集合、依赖、owner、适用不变量、批准扩展和未决风险。
