# 恢复规则

## 检查顺序

1. 确认 `study/` 位于选定工作区根目录。
2. 解析 `state.yaml` 并检查学习档案契约中的不变量。
3. 定位 `active.file`、最近完成单元和最近回顾。
4. 对照 HTML 根元素的 `data-lesson-status` 或 `data-review-status`。
5. 检查当前课程引用的概念 ID、来源 ID 和相邻导航目标。
6. 对照完成计数与综合回顾门禁。
7. 检查 `roadmap.md` 与 `concept-map.md` 是否能够由权威内容解释。

## 修复级别

### 可补建

在说明后补建缺失的 `concepts/`、`units/`、`reviews/` 空目录，或尚无内容的固定 Markdown 文件。不得用空文件覆盖已有材料。

### 可重建

在说明后从概念记录、完成课程和 `state.yaml` 重建 `roadmap.md`、`concept-map.md` 的派生部分，以及指向已存在相邻课程的导航链接。修改前保留文件中无法确认为派生内容的用户段落。

### 必须阻塞

遇到以下任一情况时停止推进并让学习者裁决：

- `state.yaml` 的完成计数与课程生命周期冲突；
- 当前活动指向多个文件或找不到权威正文；
- 两条概念记录对同一概念给出不相容定义；
- 学习契约范围发生未经确认的变化；
- 已完成课程的正文、答案或来源出现无法解释的破坏；
- 修复需要覆盖、删除或猜测用户内容。

## 恢复交接格式

```text
主题：<topic>
契约边界：<goal / scope / depth>
进度：<completed_units>；回顾 <due|not due>
当前：<unit or review / status / file>
检查点：<confirmed conclusion and reason>
未决：<questions or evidence gaps>
相关概念：<ids>
建议下一步：<one action>
修复：<none or exact repairs>
```

不要把恢复交接写成历史课程摘要；只携带继续当前工作所需的信息。
