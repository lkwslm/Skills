# 原生 provider 集成

## 支持范围

只支持以下 profile：

- `provider=openspec, mode=native`
- `provider=spec-kit, mode=native`

探测结果缺失、冲突、不可执行或 mode 非 `native` 时返回 `BLOCKED`。不要初始化第二套 provider，也不要建立平行 spec、plan 或 tasks。

## 探测与登记

1. 运行 integrate-spec-toolchain 的严格 detector。
2. 对 OpenSpec，读取其配置与 change 配置，并执行原生 status/instructions JSON 命令。
3. 对 Spec Kit，读取其状态、输入和日志，并执行原生 workflow status 命令。
4. 把 detector 的完整 JSON 输出交给 `deliveryctl observe-provider`，同时提供 repository URI、pinned commit、外部 expected revision、签名身份和受信任 Git runtime pins。不要由 agent 手工转换 operation。
5. 让命令在同一事务中保存 observation blob、登记新 profile，并按 native mapping 自动 register、supersede 或 deprecate provider artifacts。映射的 hash 与 canonicalization 必须和 Git-pinned 内容一致。
6. 用返回 revision 执行 `validate` 和 `status`；`PROVIDER_UNCHANGED` 不产生新事件。每个阶段门禁前重新探测并观察，不能把 OpenSpec 的 `done` 或 Spec Kit run status 直接映射为 Delivery 状态。只有 provider 状态变化且权威内容摘要不变时保留原 artifact identity。

后续 skill 只使用登记 profile 的原生命令和工件身份。Profile 变化必须作为新观察事件提交，并使依赖旧 profile 的工作重新过门禁。

## 权威关系

- Provider 管理规格内容与原生工作流状态。
- deliveryctl 管理跨工件身份、审批、claim、状态门禁、证据、审计和追溯。
- 两者通过完整 typed identities 和摘要关联，不复制内容。
