---
name: index-design-docs
description: 将长篇设计文档提取为带稳定身份、内容摘要和精确来源边的需求基线，并通过签名交付账本登记工件与追溯关系。用于生成 spec 前建立或更新设计基线、恢复长文档上下文、分析设计变更影响，或检查规范性内容是否完整覆盖时。
---

# 设计文档建账

执行前读取共享 [govern-delivery-artifacts](../../delivery-assurance-primitives/govern-delivery-artifacts/SKILL.md) 的 artifact、state、permission 与 evidence 协议；operation 字段以其 `scripts/delivery_core/events.py` 为唯一 schema 来源。

## 前置条件

接收仓库根目录、外部 trust root、调用方确认的 expected head、签名身份和原生 provider profile。先执行：

```text
python <deliveryctl.py> validate --root <repo> --trust-root <external-trust-root> --expected-head <expected-head> --repository-map <repository-map>
```

只接受 `openspec` 或 `spec-kit` 的 `native` profile。验证失败、profile 缺失、签名身份无权写入或发现未迁移旧账本时，返回 `BLOCKED`。不得读取当前 HEAD 代替调用方提供的 expected head。

## 工作流

1. 枚举指定设计来源，绑定完整 Git commit 或 delivery blob authority，计算规范化内容摘要，并保留 `文件#标题/行号` 定位。不得只保存摘要或引用未固定的工作树路径。
2. 先提取术语、实体、状态机、权限、数据字典和全局不变量，再提取局部需求。
3. 将规范性陈述原子化为稳定 `REQ-*`、`NFR-*`、`INV-*`、`DEC-*` 和 `OPEN-*`。保留强度、范围、依赖、验收线索与精确来源。
4. 扫描“必须、不得、仅当、至少、至多、默认、超时、容量、兼容、回滚”等限定词及数字和单位。冲突必须记录为开放问题，不得自行裁决。
5. 在原生 provider 的权威工件中写入基线内容；不要创建平行 spec、任务表或可编辑追溯表。
6. 为来源、需求和整体基线对象准备 `artifact_registered` 或 `artifact_superseded` operations；身份必须使用 `{artifact_id, version, digest}`。首次建账时为整体基线对象追加 `state_object_registered(kind=greenfield, initial_state=captured)`。
7. 为每个来源块和需求准备 `trace_node_recorded`，并用关系为 `derives` 的 `trace_edge_recorded` 建立 `source → requirement` 覆盖。依赖和冲突保留在权威需求工件中；不得发明 schema 未定义的 relation。每个规范性块至少派生一个 requirement，或被明确分类为非规范内容。
8. 把所有 operations 写入一个 JSON 数组，执行一次签名提交：

```text
python <deliveryctl.py> commit --root <repo> --trust-root <external-trust-root> --expected-revision <expected-head> --actor-id <actor-id> --signing-key <signing-key> --event-id <event-id> --at <rfc3339> --operations <operations.json> --repository-map <repository-map>
```

9. 取提交返回的 revision 作为新 expected head，立即再次 `validate`。任一步失败都返回 `BLOCKED`，不得局部补写或自动重试。

本技能不执行状态迁移。把新 revision、登记的 typed identities、未决问题和受影响的下游工件交回总控；由独立审计者产生 `audit_recorded`，再由持有目标对象 claim 的授权身份提交带 audit typed ref 的状态迁移。使用 [extraction-checklist.md](references/extraction-checklist.md) 做完整性复核，不得声称已消除所有偏差。
