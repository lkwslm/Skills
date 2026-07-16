---
name: audit-spec-conformance
description: 由独立身份依据已签名设计、批准 spec、代码版本和原始运行证据审计实现一致性，并把审计结论与状态门禁作为 typed operations 登记。用于验收单个实现任务、检测遗漏或越界变更、评估陈旧影响，或独立复核需求到证据的追溯链时。
---

# 规格一致性审计

执行前读取共享 [govern-delivery-artifacts](../../delivery-assurance-primitives/govern-delivery-artifacts/SKILL.md)；operation、record digest、typed gate ref 与 relation matrix 以其当前 schema 为准。

## 独立性与前置门禁

审计者不得是任务实现者或规格作者。接收仓库根目录、外部 trust root、调用方确认的 expected head、审计签名身份、repository map 和任务 typed identity。先执行严格 `deliveryctl validate`。

只接受 `native` 的 `openspec` 或 `spec-kit` profile。设计、spec、审批、代码、claim、运行和证据必须能通过 typed refs 与摘要闭合。审计者必须具备 `claim.write`、`run.write`、`evidence.write`、`audit.write`、`artifact.write`、`trace.write` 和 `state.write`。账本无效、expected head 不匹配、身份不独立、target commit 未固定或证据不全时判 `BLOCKED`。

## 审计流程

1. 准备 `claim_acquired`、`run_started` 和 `attempt_started`，以一个审计者签名 batch 提交并复验返回 revision。Run inputs 必须包含任务、spec、implementation 和 tests 的精确 identities。
2. 沿固定 typed trace path 重读原始设计，独立推导每个测试的期望；不得把实现者解释当作证据。
3. 验证需求、spec、任务、测试、代码和既有 evidence 的 identities、supersession 与审批关系。
4. 审查 diff：每项变更必须有任务授权，每项任务要求必须有实现映射；识别越界重构和反向修改验收标准。
5. 检出并验证账本绑定的完整 target commit 后，独立执行规定命令，检查退出码、跳过项、测试计数、环境和原始输出。必要时添加审计测试，但不得在本技能中修代码或 spec。
6. 对正例、反例、边界、非法状态、接口契约和适用 NFR 逐项判定。
7. 保存审计原始输出、canonical evidence record 和 canonical audit record 为三个 content-addressed blobs，准备 `attempt_completed`、以任务为 subject 的 `evidence_recorded` 和 `audit_recorded`。分别以对应 record blob 的 digest/authority 注册同 ID/版本工件和 trace nodes，并建立 `test verifies evidence` 与 `evidence audits audit` edges。Audit clauses 只能引用本次 evidence typed refs。
8. 仅当整体结论为 PASS 时，准备 `state_transitioned(verifying→accepted)`；gate refs 精确引用本次 PASS evidence 和 audit，且 subject、run、attempt、scope、environment 与 target commit 完全一致。随后准备 `claim_released`。FAIL 或 BLOCKED 使用 govern schema 记录真实异常状态。
9. 使用当前 expected head 执行一次审计者签名 `deliveryctl commit --blob <log-path> --blob <evidence-record-path> --blob <audit-record-path>`，再用返回的新 revision 立即 `validate`。冲突或拒绝时停止，不得覆盖、补写或自动重试。

使用 [audit-checklist.md](references/audit-checklist.md) 复核。输出 PASS、FAIL 或 BLOCKED、新 revision、逐条 typed refs 和最小复现命令。
