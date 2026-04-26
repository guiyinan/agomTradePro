# 架构整改结果（2026-04-26）

> 日期: 2026-04-26  
> 范围: `apps/`, `core/`, `shared/`, `governance/`, CI  
> 状态: 已完成

---

## 1. 结果摘要

2026-04-26 这轮架构治理已经完成，结果如下:

| 项目 | 整改前 | 整改后 |
|---|---:|---:|
| app 级双向依赖 | 30 | 0 |
| app 级 cycle component | 1 个大环 + 多个小环 | 0 |
| 架构审计债 | 209 | 0 |
| `Application -> infrastructure.repositories` | 174 | 0 |
| `shared/` 中业务 Django Model | 10 | 0 |
| application 层 `pandas/numpy` 越层导入 | 5 | 0 |

---

## 2. 本轮做了什么

### 2.1 循环依赖清零

通过以下手段将 app 级静态导入图清到 `0`:

1. 引入 `core/integration/*` 作为跨模块 bridge / facade。
2. 将部分运行时配置访问统一收口到 `core/integration/runtime_settings.py`。
3. 清理 `data_center` 对业务模块 concrete implementation 的反向 import。
4. 将高频跨模块同步查询统一改为 provider / facade / bridge 调用。

### 2.2 Application 装配路径统一

所有 application 层对 concrete repository 的依赖，统一改成:

1. `apps/*/infrastructure/providers.py`
2. `core/integration/*`

这意味着:

1. application 层不再直接 import `infrastructure.repositories`
2. concrete 装配责任回到 infrastructure / composition root
3. CI 现在可以把这一规则作为全仓硬基线

### 2.3 shared 业务模型归位

`shared/infrastructure/models.py` 不再定义业务 Django Model。  
原先 10 个配置 ORM 已迁回 owning app:

- `asset_analysis`
- `macro`
- `regime`
- `filter`
- `account`
- `hedge`
- `equity`
- `sector`
- `fund`

`shared/infrastructure/models.py` 现在只保留兼容解析，不再承担业务所有权。

### 2.4 Alpha scientific runtime 下沉

`apps/alpha/application/tasks.py` 中原本直接导入的 `pandas/numpy` 已收口到:

- `apps/alpha/infrastructure/scientific_runtime.py`

这保证 application 层不再直接依赖科学计算库。

---

## 3. 对 MCP / SDK 的影响

本轮整改**没有修改**以下对外契约:

1. MCP tool 名称
2. MCP 参数 schema
3. MCP 返回字段
4. SDK canonical API 路径
5. RBAC / audit 语义

这次同步更新的，是和 MCP 文档有关的**内部架构口径**:

1. 模块归属
2. shared 边界
3. data_center 方向
4. app 级依赖拓扑

因此:

1. `docs/mcp/*` 不需要因为这次整改重写工具契约
2. `README.md`、拓扑文档、治理文档需要反映“内部已清债”的事实

---

## 4. 当前硬基线

当前仓库的治理硬基线是:

1. app 级循环依赖必须为 `0`
2. application 层不得直接 import `infrastructure.repositories`
3. `shared/` 不得定义业务 Django Model
4. application 层不得直接 import `pandas/numpy`

对应校验:

```bash
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text
python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit
python manage.py check
```

---

## 5. 验证结果

已验证通过:

1. `python scripts/check_module_cycles.py ...` -> `Bidirectional pairs: 0`, `Cycle components: 0`
2. `python scripts/verify_architecture.py ...` -> `Audit violations: 0`
3. `python manage.py check` -> 无系统检查错误
4. 针对 `alpha / rotation / realtime / sector / qlib` 的 focused tests 通过

---

## 6. 后续事项

本轮完成的是**架构清债**，不是业务扩展。后续优先级建议:

1. 补齐与 `providers.py` / `core/integration/*` 相关的开发说明
2. 逐步把兼容解析进一步收口成明确 facade / protocol，而不是长期保留历史别名
3. 将 `config_center / portfolio / rbac` 的目标边界继续做实，而不是只停留在 bridge 层
