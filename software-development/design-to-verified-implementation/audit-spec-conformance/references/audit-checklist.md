# 独立审计检查表

## 身份与完整性

- 审计者与作者、实现者身份不同，并具备审计写入能力。
- 审计者持有目标任务的有效 claim，且 lease 与 fencing token 未过期。
- 设计、spec、任务、测试、代码、run、attempt 和 evidence 的 typed refs 全部可解析。
- 所有输入摘要与批准版本一致；superseded 或 stale 输入已阻断。
- Provider profile 为受支持的原生模式。

## 独立验证

- 期望由原始设计和批准 spec 独立推导。
- 每项代码变更有任务授权，每项强制要求有实现和测试证据。
- 正例、反例、边界、非法状态、接口与适用 NFR 已执行。
- 原始命令输出、canonical evidence record 与 canonical audit record 分别绑定独立 blob digest。

## 判定与提交

- PASS：所有强制条款通过，追溯闭合，无越界或陈旧输入。
- FAIL：有可复现偏差，并记录期望、实际、typed refs 和最小命令。
- BLOCKED：无法形成可靠判定，且缺失前提已明确。
- 只有 PASS 才提交到 `accepted` 的状态迁移，且 gate refs 指向本次审计和证据。
- Audit 与 evidence 的 subject、run、attempt、scope、environment 和 target commit 完全一致。
- 签名提交返回的新 revision 已作为 expected head 复验。
