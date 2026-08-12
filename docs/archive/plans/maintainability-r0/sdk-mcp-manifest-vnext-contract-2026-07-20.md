# R0 SDK/MCP Canonical Manifest vNext 契约

> 状态：字段与生成边界已冻结
> 构建真源：版本库内声明式 manifest；数据库仅为运行时投影与人工 override

## 1. Canonical 字段集合

| 分组 | 字段 |
|---|---|
| identity | `schema_version`、`capability_key`、`owner_app`、`title`、`summary`、`description`、`tags` |
| lifecycle | `lifecycle_status`、`deprecated_since`、`sunset_on`、`replacement_hint` |
| contract | `input_schema`、`output_schema`、`examples`、`error_contract` |
| execution | `executor_kind`、`executor_ref`、`execution_mode`、`timeout_seconds` |
| security | `risk_level`、`required_roles`、`requires_mcp_enabled`、`visibility` |
| confirmation | `requires_confirmation`、`confirmation_preview_arguments`、`confirmation_commit_arguments` |
| idempotency | `idempotency`、`idempotency_argument_name` |
| audit | `audit_tags`、`audit_event_type`、`sensitive_fields` |
| compatibility | `legacy_tool_names`、`legacy_sdk_methods`、`legacy_api_paths`、`replacement_capability_keys` |
| generation | `sdk_module`、`sdk_method`、`mcp_tool_name`、`generate_wrapper`、`runtime_handler_ref` |

vNext 的 lifecycle 四字段已在 R1A 先用于 Filter 弃用；其他新增字段在 R5 schema 批次统一落地。

## 2. 生成边界

允许生成：

- registry owner index 与聚合 `MANIFESTS`；
- 机械 SDK method/module wrapper；
- 机械 MCP tool adapter；
- capability discovery/schema 投影；
- per-owner 参数化 schema/registration/alignment 测试；
- 文档 inventory 与 ai_capability collected projection。

禁止生成：

- runtime handler 的业务逻辑；
- Django ORM 查询、事务和权限判断；
- confirmation preview 的领域语义；
- 人工 routing/visibility override；
- legacy disposition 的决策理由。

`runtime_handler_ref` 只引用人工维护实现。生成器必须拒绝引用不存在的 handler，而不是生成空逻辑。

## 3. 真源与投影

| 数据 | owner | 写入方向 |
|---|---|---|
| canonical manifest vNext | 版本库 | 人工评审后生成其他机械层 |
| SDK/MCP wrappers/index/tests | 生成物 | 只由生成器覆盖 |
| ai_capability collected fields | DB runtime projection | manifest/API/terminal collector 单向写入 |
| routing/visibility/semantic override | DB 人工治理 | 独立表/字段，不反写 manifest |
| runtime handler | 版本库人工代码 | manifest 仅引用 |

数据库不可成为 clean checkout 构建依赖，也不可反向覆盖 canonical manifest。

## 4. 确定性与 round-trip 门槛

1. clean checkout、无数据库、无 Django runtime 可生成；
2. canonical 输入排序固定，禁止把当前时间写入受版本控制生成物；
3. 连续生成两次 `git diff` 为空；
4. manifest → SDK/MCP 生成物 → ai_capability projection 不丢字段；
5. unknown field、duplicate key、missing handler、无效 role/risk/idempotency/lifecycle 均 fail closed；
6. 手写版本保留一个验证周期，生成物携带 schema/version 标识。
