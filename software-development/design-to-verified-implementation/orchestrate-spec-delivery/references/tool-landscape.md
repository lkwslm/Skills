# 可选工具选型

先用现有仓库能力落地；只有团队愿意接受对应工作流和目录约定时再引入工具。

- **GitHub Spec Kit**：适合从 constitution、spec、plan、tasks 到 implement 的通用开源流程，支持多种 coding agent。若需要成熟模板和命令入口，优先评估。
- **Kiro Specs**：适合希望 IDE 内置 requirements、design、tasks 和并行任务体验的团队。
- **OpenSpec**：适合对已有系统做持续变更，强调 proposal、spec delta 和长期 living specs 的轻量流程。
- **Tessl Spec-driven Development**：适合希望把流程与依赖文档/技能上下文组合，并用 spec 链接测试的团队。

无论选择哪个工具，额外补齐：原始设计来源定位、稳定需求 ID、基线 hash、双向追溯、实现/验收角色隔离和证据门禁。这些才直接控制偏差。

官方入口：

- GitHub Spec Kit: https://github.github.io/spec-kit/
- Kiro Specs: https://kiro.dev/docs/specs/
- OpenSpec: https://openspec.dev/
- Tessl: https://docs.tessl.io/common-workflows/spec-driven-development-with-tessl
