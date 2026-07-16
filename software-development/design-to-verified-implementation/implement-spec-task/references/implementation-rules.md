# 实施规则

## 固定操作顺序

1. 用外部 trust root 和调用方给定的 expected head 验证账本。
2. 从已批准 transition 固定审批 run、attempt、approval ref、scope、environment 和 base commit。
3. 签名提交 `claim_acquired` 与 `approved→implementing`，保存返回的新 revision 和 fencing token。
4. 用批准 base commit 执行空 diff 的 `authorize-diff`，然后运行基线、实施最小变更并执行规定验证。
5. 固定 target commit，签名登记新的 target run/attempt，等待独立审批者提交精确 target approval；随后才对 base→target 执行 `authorize-diff`。
6. 在精确 target checkout 上重跑验证；将原始输出和 canonical evidence record 分别存为 blobs，登记 attempt completion、evidence、工件和固定 relation matrix 的 trace operations。
7. 成功时登记 `implementing→verifying` 并释放 claim。
8. 用提交返回的 revision 再次验证。

## 证据要求

- 命令、参数、工作目录、环境、开始和结束时间、退出码与测试计数真实可复查。
- 证据引用精确任务、spec、代码和运行版本，而不是可变路径。
- Implementation、test、run、attempt 和 evidence 全部绑定同一个完整 target commit。
- 原始日志通过 digest 绑定，摘要不能替代原始结果。
- 跳过、flaky 重跑、人工声明和缺失输出不构成通过证据。

## 边界

- claim 不匹配、过期或 fencing token 陈旧时立即停止。
- revision 冲突时停止并交回总控重新分派。
- 任务外行为变化必须走新的变更与审批，不得顺手实现。
- 规格矛盾或不可实现时记录阻断项，不得自行放宽验收条件。
