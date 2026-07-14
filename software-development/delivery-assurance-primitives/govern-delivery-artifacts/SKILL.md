---
name: govern-delivery-artifacts
description: 通过外部信任根、Ed25519 签名、append-only 事件链、HEAD CAS、typed gate 和 pinned authority 管理或审计 `.delivery/`。用于初始化、迁移、提交、恢复、验证交付治理数据，或记录 artifact、审批、run/attempt、claim、evidence、audit、traceability 与状态转换时。
---

# 治理交付工件

## 边界

只通过 `scripts/deliveryctl.py` 读写 `.delivery/`。不直接编辑 ledger、HEAD、generation 或派生 view，不接受 unsigned JSON、调用方自报角色/权限/hash/门禁结果，不复制外部 Spec 正文。外部 trust root、私钥和 expected head 是必需输入；trust root 与私钥必须是仓库外的真实文件，拒绝 symlink/reparse。任何 Git authority 还必须显式提供绝对 `--git-executable`、`--git-sha256`、`--git-manifest` 与 `--git-manifest-sha256`；manifest 必须完整覆盖实际 Git、DLL 与 libexec 运行时树，服务会逐次复验并禁用 replace refs。

## 启动

读取项目指令和 [工件协议](references/artifact-protocol.md)、[状态机](references/state-machines.md)、[权限模型](references/permission-model.md)、[证据协议](references/evidence-protocol.md)。安装 `scripts/requirements.txt` 的强依赖；依赖缺失时停止。

## 流程

1. 新 ledger 先在仓库外运行 `deliveryctl.py bootstrap-trust`；用 `generate-key` 为各职责创建独立 actor key，审查最小权限 trust policy，再运行 `init`。不要把私钥提交到仓库。
2. 发现旧数据时只运行一次显式 `migrate-specflow` 或 `migrate-delivery`。迁移归档旧 sidecar；旧 unsigned 审批不获得授权，必须重新签署。其他命令遇到旧数据直接失败。
3. 用 schema version `1.0` 的 operation 数组调用 `commit`。每次提交显式给出外部 `--expected-revision`、actor、Ed25519 key、event ID、UTC 时间和全部 `URI=checkout` authority 映射。
4. artifact 注册或 supersede 时只用 full Git commit、provider native ID + pinned Git commit，或同 generation 发布的 content-addressed blob。CLI 从 authority 重取正文并计算 typed SHA-256；不接收 working tree 或未 pin remote。
5. approval、evidence、audit 和 transition 引用 exact ID/version/digest、event、run/attempt、scope/environment 与 target commit。claim 使用 lease token 和递增 fencing token；过期先显式记录，再重新领取。
6. 写业务代码前后运行 `authorize-diff`，用 full base/target commit 核对实际 Git diff 同时落在 signed actor scope、exact approval scope 与 active fenced claim 内；不接受调用方自报 allowed paths。
7. 事务残留时停止普通读写：完整 prepared generation 只用 `recover --expected-revision` 验证后 roll-forward；仅在明确确认尚未 prepared 的 `.building` 残留时，使用带锁的 `discard-building --expected-revision`。
8. 完成或 handoff 前运行 `validate --expected-head ... --repository-map ...`；它必须完整 replay 签名链、逐 generation 比较派生 view、重算 authority、校验 typed gate 和外部 head checkpoint。

## 输出

保留命令、退出码、JSON code、外部 head checkpoint、对象 ID/version/digest、run/attempt 和未满足条件。退出码：`0` 通过，`1` policy/gate/CAS/integrity 阻塞，`2` 输入或 schema 错误，`3` 强依赖、trust material 或 authority checkout 不可用。
