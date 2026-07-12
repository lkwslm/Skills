---
name: govern-delivery-artifacts
description: 管理两套交付 Suite 的 artifact registry、层级状态、追溯、审批、权限、陈旧传播和证据协议，并运行确定性门禁。用于初始化、验证、恢复或审计 `.delivery/` 治理工件时。
---

# 治理交付工件

## 核心边界

只管理 `.delivery/` sidecar 和确定性门禁，不复制外部 Spec 正文，不写业务代码，不代替语义审查或人工审批。已有 `.specflow/` 只读兼容，迁移需另行批准。

## 启动读取

读取项目指令、`.delivery/`、[工件协议](references/artifact-protocol.md)、[状态机](references/state-machines.md)、[权限模型](references/permission-model.md)和[证据协议](references/evidence-protocol.md)。

## 前置门禁

确认目标仓库、run ID、Suite 类型、目标 commit 和实际 capability。初始化只创建 `.delivery/`，不得初始化外部工具或改业务仓库内容。

## 执行流程

1. 用 `assets/*.schema.json` 创建或验证 registry、state、traceability、approvals、context packages 和 evidence；fallback 或导出的 Spec 另运行 `scripts/validate_spec_structure.py`。
2. 运行 `scripts/validate_delivery_artifacts.py --root <repo> --json` 验证完整目录、跨工件身份、registry 派生关系和连续状态历史；只有 `PASS` 门禁才能推进正常生命周期状态。
3. 运行 `scripts/check_delivery_traceability.py <traceability> --approvals <approvals> --registry <registry> --json` 检查 Suite 的必需关系闭包；不得通过空 `required_paths` 或调用方自定义捷径缩小完成条件。
4. 上游变化时运行 `scripts/check_delivery_staleness.py <registry> --traceability <traceability> --changed <ID@VERSION=HASH> --write --json` 标记下游 stale 闭包并输出最小复验范围。
5. 写入前运行 `scripts/check_delivery_permissions.py <manifest> --approvals <approvals> --registry <registry> --json`；环境写入必须解析到对象 ID/version/hash、范围和有效期一致的治理审批。代码变化后运行 `scripts/check_authorized_diff.py --repo <repo> --base <approved-tree> --allowed-path <scope> --json` 核对真实 diff。
6. 冻结或演进接口前运行 `scripts/check_contract.py <contract> --approvals <approvals> --registry <registry> --json`，确认审批绑定当前契约内容 hash 并覆盖全部消费者。
7. 完成声明前运行 `scripts/verify_delivery_evidence.py`，复核时间、目标 commit、工件、原始日志 hash 和未验证项；存在未验证项时不得通过完成门禁。
8. 保留历史版本、attempt、原始日志索引和每次状态转换；不得覆盖批准历史。

## 写入权限

只写治理目录中与当前角色匹配的 registry、状态、追溯、批准索引、上下文 manifest、证据索引、审计和 runs。批准正文只能由人工批准者写。

## 输出与状态

输出每项门禁的机器可读 `PASS`、`FAIL` 或 `BLOCKED`、退出码和具体缺口。生命周期状态使用小写，审批决策使用大写；不得混用三类术语。脚本退出码：`0` 通过、`1` 有效输入但门禁未满足、`2` 格式或参数错误、`3` 环境或依赖不可用。

## 失败、阻塞与陈旧

格式错误不推进状态；门禁失败 fail closed。hash 变化只传播 `stale`，不删除旧证据；清除 stale 必须引用新版本证据。

## Handoff 与完成证据

提供命令、退出码、JSON 结果、校验对象/version/hash、失败路径和未验证项。自然语言总结不能替代脚本结果。
