---
name: integrate-spec-toolchain
description: 探测仓库采用的 Spec 工具、版本、权威工件、能力和信任边界，并映射到 Suite 门禁而不复制原生正文。用于接入 Spec Kit、OpenSpec、Kiro Specs、外部规格系统或 fallback 模式时。
---

# 集成 Spec 工具链

## 核心边界

只做只读探测、能力映射和信任检查，不创建业务 Spec，不因全局 CLI 存在断言项目已采用工具，不自动安装、初始化、升级或迁移。

## 启动读取

读取项目指令、仓库工件、[探测规则](references/detection-rules.md)、[能力矩阵](references/capability-matrix.md)、[信任策略](references/trust-policy.md)和现有 `spec-tool-profile`。

## 前置门禁

确认仓库根与只读范围。执行 CLI、扩展或 workflow 前先记录来源、版本和能力；任何写入、联网、安装、迁移或凭证访问需单独授权。

## 执行流程

1. 运行 `scripts/detect_spec_tool.py --repo <repo> --json` 检查项目级标记及版本化配置；只有标记、版本、实际能力和各工件权威根均可确认时才采用 `native`。
2. 为每个候选记录 provider、模式、工件根、权威 spec/design/tasks、版本来源和信任等级。
3. 从配置而非固定默认值建立 spec/design/tasks 权威映射、命令入口和扩展清单；将原生 ID/状态映射到 Suite 追溯 ID，只保存 URI、version/hash，不复制正文。
4. 对照能力矩阵登记可复用能力和 Suite 必补门禁。
5. 同一工件有多个可写 owner 时输出 `BLOCKED`；bridge 必须指定唯一权威端和单向同步。
6. 未检测到工具时报告 `fallback` 候选；只有用户批准后才进入 `adopt`。
7. 将最终 profile 作为独立的 `spec-tool-profile` 工件登记到 artifact registry，并让 `delivery.json` 只以 ID/version/hash 引用该工件；配置变化时创建新版本并传播 `stale`。

## 写入权限

只写 `.delivery/` 中的 spec-tool profile、artifact registry 记录、权威映射和探测证据；不得写工具原生正文、初始化工具或改变其生命周期状态。

## 输出与状态

输出符合 schema 的 profile、候选、冲突、原生命令入口和缺失控制。一个工件类型只能有一个权威写入方。

## 失败、阻塞与陈旧

多工具争夺同一 spec/tasks、配置不完整、工具来源不可信或版本/权威根不可确认时 `BLOCKED`。工具配置、版本或工件根变化时 profile 及依赖映射 `stale`。

## Handoff 与完成证据

提供 profile ID/version/hash、registry 引用、provider/version/mode、权威 URI、ID 映射、允许命令、信任降级和需要授权的动作。
