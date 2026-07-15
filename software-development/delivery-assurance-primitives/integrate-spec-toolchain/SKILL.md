---
name: integrate-spec-toolchain
description: 严格探测并验证仓库已采用的 OpenSpec 或 Spec Kit 原生机器接口，输出可验证的 native ID/authority 映射或已采用 provider 的空状态。用于把现有 OpenSpec change graph 或 Spec Kit workflow run 接入 signed `.delivery` ledger；缺 CLI、无采用证据、冲突、坏布局或坏 JSON 时阻塞。
---

# 集成 Spec 工具链

## 边界

只验证仓库已经采用的 `openspec` 或 `spec-kit`。不猜 marker，不选择工具，不安装、初始化、写 provider 工件，也不生成替代 Spec。没有受支持 provider 时返回非零退出；不得创建平行数据面。

## 流程

1. 读取项目指令和 [探测规则](references/detection-rules.md)、[能力矩阵](references/capability-matrix.md)、[信任策略](references/trust-policy.md)。
2. 取得受信任的绝对 Provider CLI/原生解释器路径、入口文件、完整运行时目录 manifest 及各自 SHA-256 后，运行 `scripts/detect_spec_tool.py --repo <repo> --provider-cli <absolute-cli-or-interpreter> --provider-cli-sha256 <sha256> --provider-cli-entrypoint <entrypoint> --provider-cli-entrypoint-sha256 <entrypoint-sha256> --provider-cli-manifest <runtime-manifest> --provider-cli-manifest-sha256 <manifest-sha256> --json`，把完整 JSON stdout 原样保存到仓库外的临时文件。原生 CLI 可省略 entrypoint；只能有一个 adopted provider；manifest 必须覆盖运行时目录中的每个常规文件。
3. OpenSpec 必须有 `openspec/config.yaml`、`openspec/specs`、active change 的 `.openspec.yaml`，并成功返回 `status --json` 与 `instructions apply --json`。Spec Kit 必须有 `.specify/integration.json` 和每个 run 的 `state.json`、`inputs.json`、`log.jsonl`，且 CLI JSON 状态与磁盘一致。
4. 要求 `mode=native`、唯一 authority、runtime 版本和所有 observation hash。有活动 change/run 时 `id_mapping` 必须覆盖全部原生对象；已采用 provider 没有活动对象时允许空映射，用于 deprecate 账本中的旧对象。任何身份、状态、依赖或路径不一致都阻塞。
5. 只把 detector 输出交给 `deliveryctl.py observe-provider --profile <detector-output.json> --repository-uri <uri> --commit <full-commit> --expected-revision <expected-head> ...`。该命令在一个签名/CAS transaction 中生成 `provider_profile_observed`、register/supersede/deprecate operations 和 observation blob；不得手工拼装映射。返回 `PROVIDER_UNCHANGED` 时保持原 revision。
6. 用返回 revision 运行 `deliveryctl validate`，让 Git-pinned authority 按 profile 声明的 canonicalization 重算每个原生工件 digest。进入阶段门禁前重新执行探测与 `observe-provider`；不得把历史 observation 当作当前 OpenSpec 状态。

## 输出

输出 profile、native mapping、authority URI、runtime、observations、错误 code 和退出码。`0` 仅表示严格原生验证通过；`1` 表示 provider/布局/身份冲突，`2` 表示输入或 provider 数据格式错误，`3` 表示 CLI 环境不可用。
