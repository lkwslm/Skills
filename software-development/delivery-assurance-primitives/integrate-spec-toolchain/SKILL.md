---
name: integrate-spec-toolchain
description: 探测仓库采用的 Spec 工具、版本、权威工件、能力和信任边界，并映射到 Suite 门禁而不复制原生正文。用于接入 Spec Kit、OpenSpec、Kiro Specs、外部规格系统或 fallback 模式时。
---

# 集成 Spec 工具链

## 核心边界

只做仓库采用证据探测、受限的只读版本探测、能力映射和信任检查。不创建业务 Spec，不因全局 CLI 存在断言项目已采用工具，不自动安装、初始化、升级或迁移。

## 启动读取

读取项目指令、仓库工件、[探测规则](references/detection-rules.md)、[能力矩阵](references/capability-matrix.md)、[信任策略](references/trust-policy.md)和现有 `spec-tool-profile`。

## 前置门禁

确认仓库根与只读范围。只允许以 `shell=False` 执行配置声明的 `--version`、`version` 或 `-V` 探测；任何其他 CLI 执行、写入、联网、安装、初始化、升级、迁移或凭证访问需单独授权。

## 执行流程

1. 运行 `scripts/detect_spec_tool.py --repo <repo> --json` 检查项目级标记及版本化配置。全局 CLI 不能证明仓库已采用工具。
2. 仓库声明可执行能力时，从配置读取 executable、只读版本参数和配置声明的安装来源；解析实际路径并核对实际版本。CLI 缺失时以退出码 `3` 输出 profile 模式 `blocked` 和门禁结论 `BLOCKED`，版本不匹配时以退出码 `1` 输出同一结果，均不得降级为 fallback。
3. 只有仓库采用证据、配置版本、能力和各工件权威根均可确认，且声明可执行能力时实际运行时也通过验证，才采用 `native`。
4. 从配置而非固定默认值建立 spec/design/tasks 权威映射、命令入口和扩展清单；将原生 ID/状态映射到 Suite 追溯 ID，只保存 URI、version/hash，不复制正文。
5. 对照能力矩阵登记可复用能力和 Suite 必补门禁。同一工件有多个可写 owner 时将 profile 模式设为 `blocked` 并给出 `BLOCKED` 门禁结论；bridge 必须指定唯一权威端和单向同步。
6. 未检测到仓库采用证据时输出 `fallback`、内置格式入口、候选 provider 和待授权动作。用户请求采用工具后，只生成包含 provider、版本、来源、授权范围和重探测条件的 `adopt` handoff；由获得单独授权的执行者安装或初始化。
7. 将最终 profile 作为独立的 `spec-tool-profile` 工件登记到 artifact registry，并让 `delivery.json` 只以 ID/version/hash 引用该工件；配置、CLI 路径或实际版本变化时创建新版本并传播 `stale`。

## 写入权限

只写 `.delivery/` 中的 spec-tool profile、artifact registry 记录、权威映射和探测证据；不得写工具原生正文、初始化工具或改变其生命周期状态。

## 输出与状态

输出符合 schema 的 profile、候选、冲突、运行时证据、后续动作、所需授权、原生命令入口和缺失控制。一个工件类型只能有一个权威写入方。

## 失败、阻塞与陈旧

多工具争夺同一 spec/tasks、配置不完整、CLI 缺失、实际版本不匹配、工具来源不可信或权威根不可确认时，将 profile 模式设为 `blocked` 并给出 `BLOCKED` 门禁结论。仓库已经采用工具时不得用 fallback 掩盖环境缺失。工具配置、CLI 路径、实际版本或工件根变化时 profile 及依赖映射 `stale`。

## Handoff 与完成证据

提供 profile ID/version/hash、registry 引用、provider/version/mode、权威 URI、ID 映射、解析后的 executable、实际版本、允许命令、信任降级，以及逐项绑定授权要求的后续动作。
