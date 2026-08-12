# 学习档案契约

## 目录

在当前工作区根目录维护唯一的 `study/`：

```text
study/
├── state.yaml
├── overview.md
├── roadmap.md
├── concept-map.md
├── concepts/
├── units/
├── reviews/
└── sources.md
```

默认一个工作区只承载一个学习主题。项目分析、目标链、覆盖地图和替代设计均进入 `overview.md`、`roadmap.md` 或相应课程，不增加 `project/` 目录。

## 权威来源

| 内容 | 权威来源 | 说明 |
|---|---|---|
| 可恢复进度 | `state.yaml` | 当前活动、检查点、完成计数和回顾门禁 |
| 学习边界 | `overview.md` | 学习契约、校准结果和范围变更 |
| 概念知识 | `concepts/<concept-id>.md` | 定义、前置、推导、理解证据和来源 |
| 单元内容 | `units/NNN-slug.html` | 从草稿到完成的课程正文与课末自测 |
| 回顾内容 | `reviews/review-NNN-NNN.html` | 加权抽样、反馈和覆盖记录 |
| 来源清单 | `sources.md` | 稳定来源 ID、链接、版本和用途 |
| 当前路径 | `roadmap.md` | 从权威来源派生的线性路径与项目覆盖地图 |
| 关系导航 | `concept-map.md` | 从概念记录派生的 Mermaid 图 |

同一事实只维护在一个权威来源。派生视图引用稳定 ID，不复制长篇定义或推导。

## 状态格式

从 [`state-template.yaml`](../assets/state-template.yaml) 初始化 `state.yaml`。保持以下不变量：

- `schema_version` 为 `1`。
- `active.kind` 只能是 `none`、`unit` 或 `review`。
- `active.kind: none` 时，`number`、`status`、`file` 和 `checkpoint` 为 `null`，`unresolved_questions` 为空。
- 普通单元活动的 `status` 只能是 `draft` 或 `verification`，文件位于 `units/`。
- 回顾活动的 `status` 只能是 `draft` 或 `verification`，文件位于 `reviews/`，且 `progress.review_due` 为 `true`。
- `completed_units` 只在学习者确认普通单元完成后增加；回顾不增加该值。
- 当 `completed_units` 到达 `next_review_after` 时，将 `review_due` 设为 `true`；完成回顾后增加 `completed_reviews`，将门槛增加 10。
- 所有相对路径均以 `study/` 为基准，不写工作区绝对路径。
- `updated_at` 和检查点时间使用带时区的 ISO 8601。

## 内容格式

### `overview.md`

记录主题、学习动机、目标能力、范围内外、期望深度、阶段完成证据、起点校准和经学习者确认的范围变更。

### `roadmap.md`

记录当前位置、已完成、待验证、下一步和暂缓分支。项目主题还记录目标链与覆盖状态；覆盖项按“未调查、已定位、学习中、已覆盖、明确排除”标记。

### `concept-map.md`

保存 Mermaid 源码。节点使用不可变概念 ID，显示名可调整；边表达前置或推导关系，另用样式标示当前路径和理解状态。

### 概念记录

每个概念记录 ID、名称、定义、前置概念、推导链、相关单元、理解证据、薄弱点、复习记录和来源 ID。概念状态是反馈，不替代学习者的单元完成决定。

## 写入顺序

在推导检查点先更新当前 HTML 草稿，再更新 `state.yaml`。确认完成时依次定稿 HTML、更新概念与来源、重建路径与概念图、最后提交状态计数与活动清空。任一步失败时保留当前活动，报告部分写入，不宣称完成。
