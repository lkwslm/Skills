---
name: open-source-research
description: 作为开源项目调研流水线的用户入口，读取已有研究工件并路由输入对齐、候选发现、初筛、单项目调研或汇总阶段。
disable-model-invocation: true
---

# 开源项目调研入口

这是整条开源项目调研链路的唯一用户入口。入口只负责读取状态、调度专用 skill 和独立 subagent，不撰写研究内容，不替代任何阶段做判断。

## 先识别用户意图

- 用户没有 `research-brief.md`，或 brief 仍是草稿：调用 `open-source-research-brief`。
- 用户没有指定项目，且 brief 已确认、尚无候选发现结果：调用 `open-source-research-discovery`。
- 已有候选发现结果，但初筛卡不完整：调用 `open-source-research-screening`。
- 初筛完成且有入选项目，但深度报告不完整：对最多 10 个入选项目分别调用 `open-source-research-project`。
- 所有入选项目的深度报告完成：调用 `open-source-research-summary`。
- 用户明确指定单个仓库：先完成 `confirmed 1.0` 的 brief，再直接调用 `open-source-research-project`，跳过发现和初筛；单仓库路径在报告完成后结束。
- 用户明确指定某个阶段：只调度该阶段，但仍检查它的前置工件。

如果候选发现没有找到项目，保留 `candidate-discovery.md` 并停在候选不足状态。如果没有项目进入深度调研，不生成正式汇总报告。

## 调度规则

1. 读取 `docs/open-source-research/主题目录/research-brief.md` 的 front matter。
2. 只有 `status: confirmed` 且 `version: "1.0"` 时，才允许启动任何研究 subagent。
3. 候选发现最多产出 20 个候选；初筛结果以与 brief 的契合度为准，最多选出 10 个深度调研项目。
4. 每个候选的初筛和每个入选项目的深度调研都使用独立 subagent。每个 subagent 直接写入自己的 Markdown 产物，不派生新的 subagent。
5. brief 在确认后只读。入口可以创建目录和调度任务，但不修改 brief、筛选正文、项目报告或汇总正文。
6. 自动流水线等待全部入选项目报告完成后才汇总；用户单独调用汇总时，可以汇总现有报告，但必须标明输入不完整。

## 目录约定

```text
docs/open-source-research/主题目录/
├── research-brief.md
├── candidate-discovery.md
├── screening/
├── research-report/
└── research-summary.md
```

用 front matter 中的 `kind`、`status`、`decision` 和 `version` 判断阶段，不从文件正文猜测状态。各阶段的输入、产物和完成条件见对应 skill。

## 完成标准

入口完成调度后，应能明确说明当前阶段、已创建的任务、预期产物路径和下一阶段触发条件；入口本身不生成研究结论。
