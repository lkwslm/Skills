---
name: integrate-spec-toolchain
description: 严格探测并验证仓库已采用的 OpenSpec 或 Spec Kit 原生机器接口，输出非空 native ID/authority 映射。用于把现有 OpenSpec change graph 或 Spec Kit workflow run 接入 signed `.delivery` ledger；缺 CLI、无采用证据、冲突、坏布局或坏 JSON 时阻塞。
---

# 集成 Spec 工具链

## 边界

只验证仓库已经采用的 `openspec` 或 `spec-kit`。不猜 marker，不选择工具，不安装、初始化、写 provider 工件，也不生成替代 Spec。没有受支持 provider 时返回非零退出；不得创建平行数据面。

## 流程

1. 读取项目指令和 [探测规则](references/detection-rules.md)、[能力矩阵](references/capability-matrix.md)、[信任策略](references/trust-policy.md)。
2. 取得受信任的绝对 Provider CLI/原生解释器路径、入口文件、完整运行时目录 manifest 及各自 SHA-256 后，运行 `scripts/detect_spec_tool.py --repo <repo> --provider-cli <absolute-cli-or-interpreter> --provider-cli-sha256 <sha256> --provider-cli-entrypoint <entrypoint> --provider-cli-entrypoint-sha256 <entrypoint-sha256> --provider-cli-manifest <runtime-manifest> --provider-cli-manifest-sha256 <manifest-sha256> --json`。原生 CLI 可省略 entrypoint；只能有一个 adopted provider；manifest 必须覆盖运行时目录中的每个常规文件。
3. OpenSpec 必须有 `openspec/config.yaml`、`openspec/specs`、active change 的 `.openspec.yaml`，并成功返回 `status --json` 与 `instructions apply --json`。Spec Kit 必须有 `.specify/integration.json` 和每个 run 的 `state.json`、`inputs.json`、`log.jsonl`，且 CLI JSON 状态与磁盘一致。
4. 要求 `mode=native`、非空 `id_mapping`、唯一 authority、runtime 版本和所有 observation hash。任何身份、状态、依赖或路径不一致都阻塞。
5. 将 profile 作为 `provider_profile_observed` typed operation 提交；注册 provider artifact 时再绑定 profile digest、native ID、repository URI、full Git commit 和 path。只由 `deliveryctl commit` 写 ledger。
6. 用外部 expected head 运行 `deliveryctl validate`，让 Git-pinned authority 重新计算 profile 和原生工件 digest。

## 输出

输出 profile、native mapping、authority URI、runtime、observations、错误 code 和退出码。`0` 仅表示严格原生验证通过；`1` 表示 provider/布局/身份冲突，`2` 表示输入或 provider 数据格式错误，`3` 表示 CLI 环境不可用。
