# 交付存储与信任边界

## 权威来源

- 规格内容只存于 OpenSpec 或 Spec Kit 的原生权威目录。
- 交付身份、审批、claim、状态、运行、证据、审计和追溯只存为 deliveryctl 签名事件。
- `.delivery/` 是由 CLI 管理的账本存储，不是人工编辑接口。
- 外部 trust root 与私钥位于仓库之外。仓库内任何密钥或自声明 trust root 都不能建立信任。
- 调用方保存并传入已确认的 expected head；不得从仓库当前值推断预期状态。

## 固定写入协议

1. `deliveryctl validate --root <repo> --trust-root <external> --expected-head <expected> --repository-map <map>`
2. 生成符合 govern operation schema 的单个 JSON 数组。
3. `deliveryctl commit --root <repo> --trust-root <external> --expected-revision <expected> --actor-id <actor> --signing-key <key> --event-id <event> --at <time> --operations <ops> --repository-map <map>`
4. 把返回 revision 保存为新的 expected head。
5. 用新 revision 再次执行 `validate`。

任一步失败即停止。不要直接修改事件、HEAD、generation、索引或派生视图，也不要拆分补写失败的 batch。

## 新账本初始化

只有明确授权的新项目执行：

1. `deliveryctl bootstrap-trust --ledger-id <ledger> --private-key <external-root-private-key> --public-key <external-root-public-key> --trust-root <external-trust-root>`
2. 为职责分离的 actor 生成独立 key，审查 policy 中的 capability、path scope、environment 和有效期。
3. `deliveryctl init --root <repo> --trust-root <external-trust-root> --root-signing-key <external-root-private-key> --policy <policy.json> --actor-id <root-actor> --event-id <event> --operation-id <operation> --at <rfc3339>`
4. 用 init 返回 revision 运行固定验证协议。

## 一次性迁移

旧记录只能由总控在明确授权下执行：

- `deliveryctl migrate-specflow --root <repo> --trust-root <external> --root-signing-key <root-key> --policy <policy.json> --actor-id <actor> --event-id <event> --operation-id <trust-op> --at <rfc3339> --migration-id <id> --migration-operation-id <migration-op>`
- `deliveryctl migrate-delivery --root <repo> --trust-root <external> --root-signing-key <root-key> --policy <policy.json> --actor-id <actor> --event-id <event> --operation-id <trust-op> --at <rfc3339> --migration-id <id> --migration-operation-id <migration-op>`

首次迁移尚无 signed head，因此命令以外部 trust root 建立 genesis。若首次调用在账本提交后、旧目录清理前中断，只允许用完全相同的标识重跑并追加 `--expected-head <caller-confirmed-head>` 完成清理。迁移成功后立即验证返回 revision，并且只使用新账本。
