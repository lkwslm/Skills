# Spec 工具选型

优先复用仓库已有工具。只有未检测到工具时才提出选择；安装或初始化必须取得用户同意。

| 工具 | 可直接复用的能力 | 更适合的场景 | Suite 需要补充 |
|---|---|---|---|
| GitHub Spec Kit | constitution、spec、plan、tasks、implement、工作流、审批 gate、扩展、preset | 新系统或需要严格阶段治理的复杂功能 | 长文档分层上下文、原文追溯、独立验收；优先用扩展/preset 加门禁 |
| OpenSpec | proposal、spec delta、design、tasks、apply、verify、archive、living specs | 成熟代码库的持续增量变更 | 现状证据、影响图、生产发布与回滚门禁 |
| Kiro Specs | requirements/bugfix、design、tasks、Feature/Bug/Quick、Design-First、逐任务执行 | 使用 Kiro IDE/CLI/Web 的团队；新功能和缺陷均可 | 稳定来源 ID、跨 spec 全局不变量、独立审计和发布证据 |
| 其他工具 | 若能提供版本化需求、设计/计划、任务和状态，也可适配 | 服从项目既有实践 | 建立 profile、字段映射和缺失能力清单 |

选择原则：

- Greenfield 默认优先评估 Spec Kit；已有技术设计且团队使用 Kiro 时可采用 Kiro Design-First。
- Brownfield 默认优先评估 OpenSpec；已有 Kiro 工作流时使用 Feature 或 Bug Spec；Spec Kit 也可通过 preset、extension 和 workflow 适配。
- 团队已经采用某个工具时，迁移成本通常高于理论上的工具优势，应沿用现有工具。
- 不同时启用两个工具管理同一份 spec 或 tasks。确需协同时，必须指定唯一权威工件和只读派生方向。

官方入口：

- GitHub Spec Kit: https://github.github.com/spec-kit/
- Spec Kit Workflows: https://github.github.com/spec-kit/reference/workflows.html
- OpenSpec: https://openspec.dev/
- Kiro Specs: https://kiro.dev/docs/specs/
- Kiro CLI Specs: https://kiro.dev/docs/cli/v3/specs/
