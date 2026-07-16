# 设计提取检查表

## 来源与身份

- 每个来源工件都有稳定 `artifact_id`、版本和规范化内容摘要。
- 每个 authority 固定到完整 Git commit、原生 provider profile digest 或 delivery blob digest。
- 每个定位可回到具体文件、标题或行号。
- 内容变化通过 `artifact_superseded` 建立新旧身份关系，不覆盖旧版本。

## 需求质量

- 每个 ID 只表达一个可判定陈述。
- 约束强度、适用范围、数字、单位、默认值和异常路径未被弱化。
- 术语、实体、权限、状态机、数据字典和全局不变量已先于局部需求登记。
- 冲突和歧义带双方来源、影响范围、决策责任人和阻断级别。

## 追溯覆盖

- 来源块和需求均登记为 typed trace nodes。
- 每个规范性来源块都有 `source derives requirement` 边，非规范内容有明确分类。
- 依赖、冲突和替代说明保留在权威需求工件中，没有使用 schema 外 relation。
- 下游只引用完整 typed identity，不引用可变路径或裸字符串 ID。

## 提交门禁

- 外部 trust root 与调用方提供的 expected head 已通过验证。
- operation IDs、event ID 和 artifact versions 唯一。
- operations 由具备 `artifact.write`、`trace.write` 与 `state.write` 的身份签名提交。
- 提交返回的新 revision 已再次作为 expected head 验证。
- 本技能没有越权提交状态迁移；审计与 claimed transition 已交回总控。
