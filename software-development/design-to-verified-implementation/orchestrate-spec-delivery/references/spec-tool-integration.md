# Spec 工具集成协议

## 1. 探测

先检查项目指令和常见工件目录，再调用工具的只读版本/状态命令。记录：

- provider 与版本；
- 工件根目录；
- 原生 spec、plan/design、tasks 和状态位置；
- 可用命令或 UI 入口；
- 当前 feature/change/spec 标识；
- 已安装 extension、preset、profile 或自定义模板。

不得仅凭全局可执行文件存在就断言项目已采用该工具。不得未经同意初始化或升级工具。

## 2. 集成模式

- `native`：仓库已有工具。其原生工件是唯一权威来源，Suite 只写 sidecar 追溯和证据。
- `adopt`：仓库未使用工具，用户批准选型和初始化。之后转为 `native`。
- `bridge`：组织已有外部权威系统。明确单向同步方向和冲突处理，禁止双向隐式覆盖。
- `fallback`：用户不选择工具，才使用 `.specflow/` 内置 Markdown/CSV。

## 3. Profile

在 `.specflow/spec-tool-profile.md` 或项目等价位置记录：

```text
provider: spec-kit | openspec | kiro | other | fallback
version: <detected>
mode: native | adopt | bridge | fallback
artifact_root: <path>
authoritative_spec: <path/pattern>
authoritative_plan_or_design: <path/pattern>
authoritative_tasks: <path/pattern>
id_mapping: <native-id ↔ REQ/TEST/evidence rules>
missing_controls: <suite must add>
```

Profile 只描述映射，不复制工具工件正文。

## 4. 抽象工件映射

| Suite 抽象 | Spec Kit | OpenSpec | Kiro Specs |
|---|---|---|---|
| 治理原则 | constitution/preset | 项目约定、schema/profile | steering/project rules |
| 需求或变化 | spec | capability spec + change delta/proposal | requirements.md 或 bugfix.md |
| 技术方案 | plan | design.md | design.md |
| 任务 | tasks | tasks.md | tasks.md |
| 实施 | implement | apply | Run task / `/spec run` |
| 生命周期 | workflow/extension | verify + archive | Spec 状态与 PR 工作流 |

实际路径和命令以探测到的工具版本为准，不要依赖模型记忆硬编码。

## 5. Suite 只补充的能力

- 长设计文档的 L0/L1/L2 上下文包；
- 原文位置、来源 hash 和段落覆盖；
- 原生工件 ID 到代码、测试和证据的追溯；
- 实现与验收 agent 隔离；
- Greenfield 的跨领域契约与系统级验收；
- Brownfield 的现状基线、影响图、兼容、迁移、灰度和回滚；
- 无证据不得完成的统一门禁。

若工具已通过 extension、preset、hook 或 workflow 提供某项能力，直接复用并读取其输出，不再实现第二套检查。

## 6. 禁止事项

- 不复制一套与原生 spec 内容等价的 `.specflow/specs`。
- 不在工具 tasks 与 `.specflow/tasks.md` 之间双向同步。
- 不为了满足 Suite 命名而改写工具原生 ID；使用映射即可。
- 不绕过工具已有审批 gate 或生命周期命令直接改状态。
- 不默认安装、初始化、升级或迁移工具。
