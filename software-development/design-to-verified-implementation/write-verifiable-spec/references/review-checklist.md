# 可验证规格审查表

## 来源与身份

- 每项行为都通过 `requirement specifies spec` 指向已登记的需求版本。
- Spec、任务、测试和接口引用完整 `{artifact_id, version, digest}`。
- 原生 provider 的 ID、目录、状态和校验结果保持权威。
- Provider authority 绑定 profile digest、native ID、repository URI、完整 commit 和 path。
- 新版本通过 supersession 关系登记，未覆盖旧版本。

## 可判定性

- 每条验收条件包含前置条件、动作、可观察结果和失败判据。
- 正例、反例、边界、非法状态和恢复路径均有明确行为。
- “快速、友好、合理、正确处理、支持”等词已换成量化判据。
- 测试预言来自规格，不复制实现算法。

## 接口与 NFR

- Schema、版本、错误、幂等、顺序、超时、重试和兼容规则已冻结。
- 安全、完整性、并发、性能、恢复、可观测性、部署和迁移均有判据或不适用理由。
- 任务变更范围、依赖、验证命令和测试身份明确。

## 审批门禁

- Provider 原生校验通过。
- 审批者与作者身份不同且具备 `run.write`、`approval.write`、`claim.write` 和 `state.write`。
- `approval_recorded` 与 `draft→approved` transition 引用同一任务版本、run、attempt、scope 和 environment。
- Transition 使用审批者的有效 claim、lease token 与 fencing token。
- 签名提交后返回的新 revision 已作为 expected head 复验。
