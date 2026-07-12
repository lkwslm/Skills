---
name: audit-spec-conformance
description: 由独立 agent 逐条审计原始设计、批准 spec、代码 diff、测试和运行证据的一致性，并输出 PASS、FAIL 或 BLOCKED。用于验收按 spec 实现的任务、检测遗漏或越界变更、检查追溯矩阵、评估设计改版后的 stale 影响，以及避免实现者与测试共享同一误解时。
---

# 规格一致性审计

## 独立性

不得由该任务的实现 agent 执行。只接收原始设计定位、批准 spec、diff、测试代码和原始执行结果；不把实现者的解释或完成声明当作证据。

## 审计流程

1. 读取 Spec 工具 profile，确认权威工件位置和 ID 映射；校验设计基线 hash、原生 spec 版本/hash 和审批记录。过期或未批准时判 `BLOCKED`。
2. 沿来源引用重读原文，独立推导每个 `TEST-*` 的期望；检查 spec 是否歪曲或遗漏原设计。
3. 确认 `source-coverage.csv` 无遗漏，再运行 `python scripts/check_traceability.py .specflow/traceability.csv`。追溯矩阵可以引用 Spec Kit/OpenSpec/Kiro 的原生工件和任务 ID，不要求复制其内容；前者是原文覆盖表，后者是跨工具交付追溯，不得混用。
4. 审查 diff：每项变更必须有任务授权；任务要求必须有实现映射；识别越界重构和反向修改验收标准。
5. 独立执行指定命令。检查退出码、跳过项、测试计数、环境和产物，而非复述实施报告。
6. 对正例、反例、边界、非法状态及关键不变量做需求级黑盒检查；关键规则必要时补充审计测试，但不得在审计中修实现。
7. 检查接口契约和适用 NFR；每项必须有证据或明确批准的人工验收记录。
8. 使用 [audit-template.md](assets/audit-template.md) 逐条输出结论。

## 判定

- `PASS`：所有强制条款和追溯均有复核证据，无越界或陈旧工件。
- `FAIL`：存在可复现的不符合。给出 ID、期望、实际、证据和最小复现命令。
- `BLOCKED`：基线过期、审批缺失、环境不可用、测试不稳定或证据不足，无法可靠判定。

只有审计者可以建议从 `verifying` 转为 `accepted`；最终审批仍服从项目规则。不得在本技能中修改代码或 spec。
