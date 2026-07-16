# 受支持 provider

## OpenSpec

适用于以 change 为中心、由原生配置和 instructions/status 命令管理规格生命周期的仓库。只有 detector 能读取配置并成功执行所需 JSON 命令时才可用。

## Spec Kit

适用于由原生 state、inputs、log 和 workflow status 管理规格、计划与任务的仓库。只有 detector 能解析这些状态并成功执行工作流命令时才可用。

## 选择规则

- 仓库已采用其中一个 provider 时，使用该 provider 的原生 profile。
- 同时检测到两个 provider、没有检测到 provider，或命令能力不完整时停止并要求负责人解决。
- Provider 负责规格内容；deliveryctl 负责签名治理记录。不得让任一侧复制另一侧的权威数据。
