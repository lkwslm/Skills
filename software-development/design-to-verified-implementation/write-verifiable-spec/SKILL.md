---
name: write-verifiable-spec
description: 将已解决冲突的需求基线转换为 OpenSpec 或 Spec Kit 原生的可审查规格、接口契约和任务，并把审批与追溯作为签名 typed operations 登记。用于编写或修订可机械验收的 spec、冻结接口、切分任务，或检查规格是否足以指导实现时。
---

# 可验证规格编写

执行前读取共享 [govern-delivery-artifacts](../../delivery-assurance-primitives/govern-delivery-artifacts/SKILL.md)；所有 operation、identity、authority 和 gate ref 字段严格使用其当前 schema。

## 前置门禁

接收仓库根目录、外部 trust root、调用方确认的 expected head、签名身份、repository map 和已登记的需求 typed identities。先执行 `deliveryctl validate`，参数必须包含 `--trust-root` 和 `--expected-head`。

只接受已登记为 `native` 的 `openspec` 或 `spec-kit` profile。需求来源摘要不匹配、存在高影响开放问题、provider 不受支持，或作者身份缺少 `trace.write`、`state.write` 任一能力时，返回 `BLOCKED`。另需一个具备 `provider.write`、`artifact.write` 且 scope 覆盖 provider 根目录的 `spec-integrator`；不得由作者兼任 integrator 或创建通用规格副本。

## 工作流

1. 选择一个端到端切片，列出关联需求 typed identities 和明确非目标；沿 trace edges 重读原文。
2. 仅使用已选 provider 的原生命令和目录编写或修订 spec、design/plan 与 tasks，并保留原生 ID 和状态。
3. 把行为写成可观察契约，覆盖正例、反例、边界、失败和非法状态。
4. 冻结 schema、版本、错误模型、幂等、顺序、超时、重试、兼容和责任方。
5. 对安全、数据完整性、并发、性能、恢复、可观测性、部署、迁移、回滚和兼容逐项量化，或记录不适用理由。
6. 切分可独立验证的任务，记录依赖、允许和禁止修改范围、完成命令及测试身份。
7. 运行 provider 原生校验，把候选工件固定到完整 Git commit。校验失败或只有未提交工作树路径时停止，不得用本地宽松检查替代。
8. 在该 commit 上重新运行 detector；由独立 `spec-integrator` 把完整输出交给 `deliveryctl observe-provider`。不得手工构造 provider authority 或 spec/task 的 `artifact_registered`。用返回 revision 立即执行 `validate` 和 `status`，从已验证状态取得新 spec/task typed identities。
9. 作者以上一步 revision 为 expected head，只登记 spec/task trace nodes、`requirement specifies spec` 与 `spec derives task` edges；为每个尚无状态的新 task 提交 `state_object_registered(kind=task, initial_state=draft)`。内容未变而只有 provider 运行状态变化时复用原 identity；内容变化产生新 identity，并重新进入 draft/审批流程。
10. 使用作者签名执行一次 `deliveryctl commit`，随后用返回 revision 立即执行 `validate` 和 `status`。revision 冲突、identity 不在 verified status 中或任一 operation 被拒绝时返回 `BLOCKED`，不得自动重试。

规格作者到此停止。总控必须把新 revision 交给不同的授权审批者；审批者在一个签名 batch 中依次提交 `run_started`、`attempt_started`、task 的 `approval_recorded`、`claim_acquired`、`state_transitioned(draft→approved)` 和 `claim_released`，并立即复验 revision。审批、transition 与 run/attempt 必须绑定同一 task、scope、environment 和 target commit。使用 [review-checklist.md](references/review-checklist.md) 复核并输出规格与任务 typed identities、审批状态和未决阻断项。Spec 作者不得批准自己的工件或开始实现。
