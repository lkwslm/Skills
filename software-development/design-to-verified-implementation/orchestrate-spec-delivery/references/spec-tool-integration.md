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
4. 将 `profile_id`、provider、`native` mode、provider version、repository URI、pinned commit、ID mapping 和 observation time 写入 `provider_profile_observed` operation。原生命令能力留在 detector 输出，不得塞入 operation schema 未定义字段。
5. 签名提交该 operation，并用返回 revision 复验。

后续 skill 只使用登记 profile 的原生命令和工件身份。Profile 变化必须作为新观察事件提交，并使依赖旧 profile 的工作重新过门禁。

## 权威关系

- Provider 管理规格内容与原生工作流状态。
- deliveryctl 管理跨工件身份、审批、claim、状态门禁、证据、审计和追溯。
- 两者通过完整 typed identities 和摘要关联，不复制内容。
