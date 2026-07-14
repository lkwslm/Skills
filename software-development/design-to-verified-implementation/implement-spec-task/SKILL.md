---
name: implement-spec-task
description: 在已签名批准的 OpenSpec 或 Spec Kit 原生任务下领取独占 claim，以测试和最小代码变更实现验收条件，并把运行、尝试和证据登记到签名交付账本。用于严格按批准 spec 实现单个任务、继续下一项任务，或修复独立审计确认的规格偏差时。
---

# 按规格单步实施

执行前读取共享 [govern-delivery-artifacts](../../delivery-assurance-primitives/govern-delivery-artifacts/SKILL.md)；不得根据示例猜测 operation 或 gate 字段。

## 前置检查

接收仓库根目录、外部 trust root、调用方确认的 expected head、实现者签名身份、repository map 和任务 typed identity。先用 `deliveryctl validate --expected-head <expected-head>` 验证账本。

确认 provider 为 `native` 的 `openspec` 或 `spec-kit`，任务已有独立签名审批，依赖已接受，基线与 spec 摘要未变化，变更范围明确；实现者还必须具备 `claim.write`、`state.write`、`run.write`、`artifact.write`、`trace.write` 和 `evidence.write`。任一条件不满足即 `BLOCKED`。

## 实施流程

1. 读取任务 `draft→approved` transition 所绑定的审批 run、attempt 和 approval typed ref；其 target commit 是本次实施的批准 base commit。
2. 准备 `claim_acquired`，随后以该审批上下文准备 `state_transitioned(approved→implementing)`。将两项作为一个签名 batch 提交并复验返回 revision。claim 冲突时停止，不得换 ID 抢占或自动重试。
3. 使用 `deliveryctl authorize-diff` 对批准的 base commit 执行 `base=target` 空 diff 权限检查，参数必须绑定当前 expected head、repository map、actor、claim/lease/fencing、审批 run/attempt、environment 和 UTC time；失败时停止。
4. 只读取当前任务、其 spec、直接来源、相关接口和必要代码。复述可观察完成条件、允许范围和验证命令。
5. 运行现有基线测试。修复缺陷时先复现失败；新增行为时先加入失败的验收或契约测试。
6. 做满足当前任务的最小变更。不得修改 spec、审批、测试预言或设计解释来迁就实现。
7. 运行任务测试、受影响回归、接口契约检查及 spec 指定的 E2E/NFR 检查。禁止把跳过、偶然成功或缺失输出计为通过。
8. 通过授权的版本控制步骤把代码和测试固定到完整 target commit；未产生 pinned commit 时返回 `BLOCKED`。实现者为该 target commit 提交新的 `run_started` 和 `attempt_started`，复验 revision 后停止等待独立审批者。
9. 独立审批者审查精确的 `base→target` diff 后，只能为这个新 run/attempt、target commit、scope 和 environment 提交一个当前有效的 `APPROVED`。实现者取得其返回 revision 后运行 `deliveryctl authorize-diff`；缺少精确 target approval、出现多个匹配 approval 或 diff 越界均停止。不得复用 base approval。
10. 在精确检出的 target commit 上重新运行规定验证，只把这次输出作为证据。将原始输出和 evidence record 的 canonical JSON 分别保存为 content-addressed blobs，准备 `attempt_completed` 和以任务为 subject 的 `evidence_recorded`；以 evidence record blob 的 digest/authority 注册同 ID/版本 evidence 工件，同时注册 implementation、test 工件及三者 trace nodes，并只建立 `task implements implementation`、`implementation derives test`、`test verifies evidence` edges。
11. 成功时准备 `state_transitioned(implementing→verifying)`，gate refs 精确引用本次 PASS evidence，且 transition 复用 target run/attempt/scope/environment/commit 与当前 claim fencing 数据；随后 `claim_released`。失败或环境不可用时只提交真实 attempt/evidence 并释放 claim，再交给独立审计者决定 `failed` 或 `blocked` transition；不得由实现者自建 audit 或伪造成功证据。
12. 将完成 operations、原始日志和 canonical evidence record 作为一个签名 batch，用当前 expected head 执行 `deliveryctl commit --blob <log-path> --blob <evidence-record-path>`，再用返回的新 revision 立即 `validate`。陈旧 revision、claim 失效或签名拒绝均返回 `BLOCKED`。

使用 [implementation-rules.md](references/implementation-rules.md) 复核。输出新 revision、diff 范围、证据 typed refs、未验证项和审计所需输入。实现者无权标记 `accepted`。
