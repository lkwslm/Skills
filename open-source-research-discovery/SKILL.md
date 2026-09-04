---
name: open-source-research-discovery
description: 读取 confirmed 1.0 的 research brief，按用户确认的发现偏好寻找最多 20 个开源项目候选并写入简短清单。
---

# 开源项目候选发现

只负责发现候选，不负责判断最终适配性。它是项目初筛的输入阶段。

## 输入门槛

- 先读取主题目录下的 `research-brief.md`。
- brief 必须是 `status: confirmed`、`version: "1.0"`。
- brief 已指定明确仓库时，跳过本阶段，直接交给 `open-source-research-project`。
- 发现偏好缺少会改变候选范围的决策时，返回 brief 阶段补充，不自行猜测。

## 发现规则

1. 按 brief 中的目标问题、必须能力、硬约束、解决思路偏好和候选发现偏好搜索。
2. 最多保留 20 个候选。Stars、维护活跃度等只有在 brief 中被写为硬约束时才是淘汰条件，否则只用于排序和说明。
3. 对每个候选确认官方仓库；无法确认官方项目身份的候选不进入清单。
4. 重要事实回到官方仓库、官方文档、许可证、Release 或维护记录核验。
5. 每个候选只写一行简要说明，不提前展开设计、部署或适配分析。
6. 由一个独立 discovery subagent 完成发现，并直接写入 `candidate-discovery.md`；该 subagent 不派生新的 subagent。

## 产物

使用 [references/discovery-template.md](references/discovery-template.md) 写入：

```text
docs/open-source-research/主题目录/candidate-discovery.md
```

front matter 至少包含 `kind: open-source-research-discovery`、`status: completed`、`candidate_limit: 20` 和 `topic`。

如果没有候选，仍写入清单，记录搜索范围、条件和无结果原因，然后停止流水线。不得放宽硬约束。

## 完成标准

`candidate-discovery.md` 已列出不超过 20 个、身份可确认且有官方来源的候选，或明确记录没有找到候选的原因；文件不包含深度调研结论。
