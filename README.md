# System Delivery Skill Suites

本仓库提供一组面向 Codex/AI agent 的系统交付 Skills，用版本化工件、状态机、权限边界、双向追溯和可复核证据约束软件交付过程。

它解决两类不同问题：

- **Greenfield：新系统整体实现**——从已批准的系统设计出发，建立系统基线、分层上下文、冻结契约和垂直切片，最后进行独立系统验收。
- **Brownfield：生产系统增量变更**——从限定变更意图出发，先确认真实现状和影响范围，再实施最小变化，并经过兼容、回归、发布和恢复门禁。

完整架构与创建合同见 [SYSTEM-DELIVERY-SKILL-SUITES.md](software-development/SYSTEM-DELIVERY-SKILL-SUITES.md)。

## 如何选择 Suite

| 场景 | 顶层入口 | 说明 |
|---|---|---|
| 根据完整设计创建一个新系统 | `$orchestrate-system-realization` | 设计是主要事实来源，强调全局一致性、跨域契约和系统级验收 |
| 修改已有生产系统、修复缺陷或执行局部迁移 | `$orchestrate-production-change` | 代码、配置、运行行为、契约和批准意图共同构成事实来源，强调兼容、灰度和恢复 |
| 大型重构、平台迁移或在旧系统中建设新子系统 | `$orchestrate-production-change` | 使用 Brownfield 总控作为唯一顶层 owner，在内部委托 Greenfield 子流程；最终状态仍由生产验证决定 |
| 从长篇设计分解规格并逐任务实现、审计 | `$orchestrate-spec-delivery` | 用原生 OpenSpec/Spec Kit 与签名 `.delivery` 账本记录需求、规格、任务和进度 |
| 只初始化、恢复或审计 `.delivery/` 工件 | `$govern-delivery-artifacts` | 运行状态、审批、权限、追溯、陈旧传播和证据门禁 |
| 只探测仓库已有的 Spec 工具 | `$integrate-spec-toolchain` | 严格识别原生 OpenSpec 或 Spec Kit；缺失、冲突或未固定运行时均 fail closed |

不要同时启动两个可写总控。混合流程必须由 `$orchestrate-production-change` 持有父变更、迁移、发布和最终状态。

## 安装或加载

每个 Skill 都是包含 `SKILL.md` 和 `agents/openai.yaml` 的独立目录。可采用以下任一方式：

1. 在当前仓库工作时，向 Codex 明确提供 Skill 名称和目录，例如：

   ```text
   使用 $orchestrate-system-realization，Skill 位于
   software-development/design-to-system-realization/orchestrate-system-realization，
   根据 docs/design/ 下的已批准设计开始新系统交付。
   ```

2. 需要全局使用时，将以下四个目录下的 21 个 Skill 子目录分别安装到 `$CODEX_HOME/skills/`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills/`：

   ```text
   software-development/design-to-system-realization/
   software-development/design-to-verified-implementation/
   software-development/production-change-to-verified-release/
   software-development/delivery-assurance-primitives/
   ```

安装时保持每个 Skill 目录名不变，并避免覆盖同名目录中的本地修改。重新启动或刷新 Codex 会话后，通过 `$skill-name` 调用。

Windows checkout 需要让 Git 支持长路径（例如 `git config --global core.longpaths true`），或把仓库放在较短的根目录；签名 generation 与 content-addressed blob 的文件名不能截断或改写。

## 推荐使用方式

### 新系统整体实现

入口提示词示例：

```text
使用 $orchestrate-system-realization，根据 docs/design/ 中已批准的设计实现新系统。
先建立 .delivery 治理工件并探测现有 Spec 工具；在契约冻结和任务批准前不要编码。
没有独立验证证据时不得把系统标记为 verified。
```

标准顺序：

```text
orchestrate-system-realization
  → establish-system-design-baseline
  → partition-system-contexts
  → freeze-system-contracts
  → write-system-slice-spec
  → implement-system-slice
  → verify-system-realization
```

### 生产系统增量变更

入口提示词示例：

```text
使用 $orchestrate-production-change 处理这个生产变更。
先从目标 commit、测试、契约、配置和脱敏运行证据建立当前行为；
确认 blast radius 和 Delta Spec 后再实施。没有生产授权时停在 release_ready。
```

标准顺序：

```text
orchestrate-production-change
  → discover-current-system-behavior
  → analyze-production-change-impact
  → write-production-delta-spec
  → implement-bounded-production-change
  → verify-production-change
  → control-production-release
```

总控会先调用 `$govern-delivery-artifacts` 和 `$integrate-spec-toolchain`。通常应从总控开始，而不是手工跳过前置阶段直接调用实施 Skill。

### 设计到可验证实现

```text
orchestrate-spec-delivery
  → index-design-docs
  → write-verifiable-spec
  → implement-spec-task
  → audit-spec-conformance
```

该流程适合像本仓库一样由设计驱动、同时需要让 OpenSpec 结果与 `.delivery` 状态对齐的项目。Provider 负责可编辑的 spec/task 正文；账本记录固定身份、审批、claim、生命周期和证据。

## 21 个 Skills 的用途

### 共享治理与工具集成

| Skill | 何时使用 | 主要结果 |
|---|---|---|
| `govern-delivery-artifacts` | 初始化、验证、恢复或审计 `.delivery/`；执行状态、审批、权限、追溯、陈旧和证据门禁 | 统一 registry、状态记录、门禁结果和可复核证据 |
| `integrate-spec-toolchain` | 接入已有原生 Spec Kit 或 OpenSpec；核对 CLI 的实际路径、版本和完整运行时 | Spec 工具 profile、运行时证据、权威工件映射、能力缺口和信任边界 |

### Design-to-Verified Skills

| Skill | 何时使用 | 主要结果 |
|---|---|---|
| `orchestrate-spec-delivery` | 从设计启动或恢复规格驱动交付 | 已验证 revision、provider、ready/blocked 任务和下一步 |
| `index-design-docs` | 把长设计原子化为稳定需求并建立来源覆盖 | Git-pinned 来源、需求、基线和 trace nodes/edges |
| `write-verifiable-spec` | 把需求写入原生 provider 并由独立身份登记 | 原生 spec/task、provider observation、审批与任务初始状态 |
| `implement-spec-task` | 实施一个已批准且依赖满足的任务 | 有 claim 约束的最小 diff、测试和 evidence |
| `audit-spec-conformance` | 独立验证任务是否满足规格 | 条款级 audit、trace closure 和 accepted/blocked 结论 |

### Greenfield Skills

| Skill | 何时使用 | 主要结果 |
|---|---|---|
| `orchestrate-system-realization` | 启动或恢复新系统交付、协调专职角色、执行系统完成门禁 | Greenfield 状态、角色任务、门禁和系统完成报告 |
| `establish-system-design-baseline` | 编码前消化长设计、ADR、领域文档和 NFR，或分析设计变化 | 稳定需求 ID、术语、不变量、来源覆盖和开放问题 |
| `partition-system-contexts` | 长设计需要按领域分层，或要为切片提供最小完备上下文 | L0/L1 context packages、ownership 和依赖图 |
| `freeze-system-contracts` | 多角色并行前冻结跨模块接口、事件和共享数据，或审批契约演进 | 版本化契约、消费者、兼容窗口和契约测试 |
| `write-system-slice-spec` | 把系统基线和冻结契约转成端到端、可验证的垂直切片 | Slice Spec、任务图、测试定义和 L2 context package |
| `implement-system-slice` | 实施一个已批准、未陈旧的 Greenfield 任务，或修复该任务的审计偏差 | 最小代码 diff、测试和实施 evidence；状态只到 `verifying` |
| `verify-system-realization` | 独立验收切片或判断整个系统是否达到 `verified` | 条款级 PASS/FAIL/BLOCKED、跨域集成和系统级验收结果 |

### Brownfield Skills

| Skill | 何时使用 | 主要结果 |
|---|---|---|
| `orchestrate-production-change` | 修改生产系统、恢复中断变更或管理混合流程 | 父变更状态、风险、角色任务、发布准备度和最终报告 |
| `discover-current-system-behavior` | 修复缺陷、迁移或变更前确认真实运行行为 | 当前行为基线、代码/数据流地图、`DISC-*` 和置信度 |
| `analyze-production-change-impact` | 确定直接和间接影响、回归范围、风险和发布门禁 | Blast-radius map、消费者、数据/配置风险和验证范围 |
| `write-production-delta-spec` | 将已评审影响转成明确的改变/保持不变条款和部署任务 | Delta Spec、兼容矩阵、迁移、观测、停止和恢复方案 |
| `implement-bounded-production-change` | 实施一个批准的 Brownfield 任务，或修复其验证偏差 | 最小且可恢复的 diff、回归/目标测试和实施 evidence |
| `verify-production-change` | 独立检查新增、修改、保持不变、迁移和实际 diff 范围 | 条款级审计及 `implementation_accepted`/`release_ready` 建议 |
| `control-production-release` | 检查发布准备度，或在明确人工授权下执行灰度、停止、回滚和恢复 | 发布计划、授权动作日志、指标和生产验证 evidence |

## 共享数据如何贯通

所有 Skills 通过目标业务仓库中的 `.delivery/` sidecar 共享状态，不依赖聊天历史：

```text
.delivery/
├─ HEAD.json
├─ generations/
│  └─ <sequence>-<event-hash>/
│     ├─ event.json
│     ├─ manifest.json
│     ├─ state.json
│     └─ views/
└─ .transactions/
```

`HEAD.json` 只是签名事件链的仓库内头；外部 trust root、私钥和调用方确认的 expected head 不得提交。跨记录引用统一使用 `artifact_id + version + typed digest`。恢复时先完整 replay 和 authority 校验，再用 `deliveryctl status --progress-only` 读取 provider、provider/delivery 漂移、任务状态、依赖、claim、ready 集合和 trace 覆盖；不得从聊天历史推断进度。

OpenSpec/Spec Kit 的正文始终由 provider writer 维护。Detector 生成稳定映射，`deliveryctl observe-provider` 将映射签名登记到 ledger；OpenSpec 每个标准 checkbox 和 Spec Kit 每次 run 都有独立的 delivery task 身份。状态变化不会伪造新的内容身份。

术语必须严格区分：

- 门禁结果：`PASS`、`FAIL`、`BLOCKED`；
- 生命周期状态：`blocked`、`failed`、`stale` 等小写状态；
- 审批决策：`APPROVED`、`REJECTED`、`RISK_ACCEPTED`。

## 安全边界

- Skills 默认不安装、初始化、升级或迁移外部 Spec 工具；本仓库的自托管试点是经过明确授权的例外。
- 未采用受支持 provider、同时采用多个 provider、CLI 缺失或运行时未固定时结论为 `BLOCKED`，不得创建第二套平行规格。
- 分析和 dry-run 不修改目标业务代码，不连接或发布生产系统。
- 实现者不得修改设计基线、Spec、审批、冻结契约或测试预言来迁就实现。
- 验证者不得在验证过程中修复实现或改写 Spec。
- 环境写入必须解析到 `.delivery/approvals.json` 中与对象 ID/version/hash、环境、范围和有效期一致的批准记录。
- 没有生产权限时，Brownfield 流程只能停在 `release_ready` 并输出 handoff，不得伪造 `released` 或 `production_validated`。
- 不同 agent 不等于已形成技术权限隔离；无法落实关键 capability 边界时必须 fail closed。

## 验证本仓库中的 Skills

在仓库根目录执行：

```powershell
$env:PYTHONUTF8 = '1'

python -m unittest discover `
  -s software-development/delivery-assurance-primitives/govern-delivery-artifacts/scripts/tests `
  -v

python -m unittest discover `
  -s software-development/delivery-assurance-primitives/integrate-spec-toolchain/scripts/tests `
  -v

python -m unittest discover `
  -s software-development/tests `
  -v
```

每个 Skill 还应使用当前 Codex 安装中的 `skill-creator/scripts/quick_validate.py` 单独验证。不要在脚本或 Skill 中硬编码某个用户主目录下的验证器路径。
