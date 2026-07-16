---
name: orchestrate-spec-delivery
description: 以 deliveryctl 签名账本编排从长篇设计到原生 OpenSpec 或 Spec Kit 规格、单任务实施和独立审计的交付闭环。用于建立阶段门禁、组织分离角色、恢复中断项目，或对旧交付记录执行一次性迁移时。
---

# 规格交付总控

执行前读取共享 [govern-delivery-artifacts](../../delivery-assurance-primitives/govern-delivery-artifacts/SKILL.md) 与 [integrate-spec-toolchain](../../delivery-assurance-primitives/integrate-spec-toolchain/SKILL.md)；不得复制或改写它们的 CLI、schema 和 provider 判定规则。

## 不可变契约

只把签名账本重放结果和已登记的原生 provider 工件视为事实来源。所有写入必须通过 `deliveryctl` typed operations；不得直接编辑生成视图、HEAD、事件或索引。

正常路径只接受 `native` 的 `openspec` 或 `spec-kit`。缺少受支持 provider 时返回 `BLOCKED`。外部 trust root、签名密钥和调用方确认的 expected head 必须由调用方提供；不得从仓库内部推断信任根或把当前 HEAD 当作预期值。

## 启动流程

1. 读取项目规则、仓库状态、设计入口和 [project-layout.md](references/project-layout.md)，只判定 signed ledger、旧存储或无账本三种状态，不读取旧记录内容。
2. 已有 signed ledger 时，从 `.delivery-project.json` 定位 CLI、外部 trust/checkpoint 和 Git runtime，设置 `PYTHONDONTWRITEBYTECODE=1`，用调用方给定的 expected head 运行 `deliveryctl validate`，随后用完全相同的 authority pins 运行 `deliveryctl status --progress-only`；失败即停止。只用返回的 `progress` 恢复 provider、provider/delivery 对齐、任务、依赖、claim 和下一步。
3. 无账本时，仅在明确授权的新项目中由独立管理身份执行 `deliveryctl bootstrap-trust` 和 `deliveryctl init`。把 init 返回 revision 设为 expected head 并立即验证；不得自动生成、存放或替换 trust material。
4. 检测到旧存储时，只允许在用户明确授权、提供唯一 migration ID/operation ID 和签名身份后执行一次 `deliveryctl migrate-specflow` 或 `deliveryctl migrate-delivery`。迁移后把返回 revision 设为 expected head 并立即验证；不得继续读写旧记录。
5. 除上述三种分支外均返回 `BLOCKED`。任何分支未得到已验证 expected head 时不得探测或写入 provider。
6. 按 [spec-tool-integration.md](references/spec-tool-integration.md) 严格探测 provider，并由独立 spec-integrator 调用 `deliveryctl observe-provider` 登记 profile 和 provider-backed artifact；不得手工构造 `provider_profile_observed` 或 provider authority。探测不唯一或非原生时停止。
7. 调用 `$index-design-docs` 建立带 typed trace graph 的需求基线；阻断高影响冲突和缺失决策。
8. 调用 `$write-verifiable-spec` 修订 provider 原生 spec、design/plan 和 tasks，并由不同授权身份签名批准。
9. 每次只把一个依赖满足且已批准的任务交给 `$implement-spec-task`。实现者必须先取得签名 claim。
10. 用不同身份调用 `$audit-spec-conformance`。审计者必须取得任务 claim；只有 subject、run、attempt、scope、environment 和 target commit 全部匹配的 audit/evidence typed gate refs 才能推进到 `accepted`。
11. 每次提交都使用上一步返回的 revision 作为下一步 expected head，并立即执行 `validate` 和 `status`。revision 冲突时停止并让调用方重新确认，不得自动重试。

## 角色隔离

- 建账者只提取、登记来源与追溯。
- Spec 作者定义可观察行为，不批准自己的工件。
- 实现者只修改领取任务允许的范围，不能改变 spec。
- 审计者独立推导预期，不接受实现者声明作为证据。
- 授权负责人签署解释、审批、信任与重大变更。

无法满足身份或权限隔离时返回 `BLOCKED`，不得由同一身份兼任门禁角色。

## 状态门禁

状态由签名事件重放派生，不由可编辑文件维护。整体 Greenfield 状态为：

`captured → baselined → planned → executing → verified → closed`

任务状态为：

`draft → approved → implementing → verifying → accepted`

任何状态迁移都必须由目标对象的有效 claim 授权，并携带 operation schema 要求的 typed gate refs。设计或 spec 变更通过 supersession 和新状态事件使下游失效；不得修改历史记录。

完成时报告最新已验证 revision、provider profile、已接受/阻塞/失效任务、trace graph 覆盖、独立审计证据和仍需人工决定的事项。没有签名 typed evidence 的完成声明视为未完成。
