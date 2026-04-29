# AgomTradePro 宏观数据治理编码规范

## 1. 总原则

宏观数据治理已经统一收口到 `data_center`。新增或修改宏观链路代码时，必须满足：

1. 指标定义只来自 `IndicatorCatalog`
2. 单位与量纲规则只来自 `IndicatorUnitRule`
3. 宏观事实只存 `data_center_macro_fact`
4. 页面/API 只读 `/api/data-center/macro/series/`
5. 不得引入旧单位配置模型、硬编码单位表、legacy fallback

## 2. 单位规则规范

`IndicatorUnitRule` 是唯一量纲治理表，字段含义如下：

- `indicator_code`
- `source_type`
- `dimension_key`
- `original_unit`
- `storage_unit`
- `display_unit`
- `multiplier_to_storage`
- `priority`
- `is_active`
- `description`

规则匹配顺序：

1. 精确匹配 `indicator_code + source_type`
2. 回退匹配 `indicator_code + source_type=""`
3. 仍未命中则同步失败，不得代码兜底

## 3. 数据流规范

### 3.1 入库

- 采集适配器只返回原始值、来源和原始单位
- `SyncMacroUseCase` 负责读取 `IndicatorUnitRule`
- 用 `multiplier_to_storage` 计算 canonical storage value
- `MacroFact.value` 存 canonical value
- `MacroFact.unit` 存 canonical storage unit
- `MacroFact.extra.original_unit` 持久化原始单位

### 3.2 查询

宏观时序响应必须同时携带：

- `value`
- `unit`
- `display_value`
- `display_unit`
- `original_unit`

其中：

- `value/unit` 供内部计算
- `display_value/display_unit` 供页面展示
- `original_unit` 供审计与巡检

## 4. 页面与接口规范

### 4.1 允许的宏观接口

- `GET /api/data-center/macro/series/`
- `POST /api/data-center/sync/macro/`
- `GET/POST /api/data-center/indicators/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/`
- `GET/POST /api/data-center/indicators/{code}/unit-rules/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/`

### 4.2 禁止项

- 新增旧 macro API 前缀
- 新增旧单位配置模型
- 新增硬编码单位常量表
- 新增 `IndicatorService.INDICATOR_METADATA`
- 通过 system settings JSON 人工维护宏观指标目录

## 5. 新增指标操作规范

新增一个宏观指标时：

1. 先建 `IndicatorCatalog`
2. 再建 `IndicatorUnitRule`
3. 最后补 provider/fetcher 抓取逻辑

如果新增指标需要改代码里的单位映射，说明方案错误，应改为补治理数据。

## 6. 测试护栏

必须覆盖：

- 指标 CRUD
- 单位规则 CRUD
- `display_value/display_unit/original_unit` 契约
- 关键指标如 `CN_GDP`、`CN_M2`、`CN_CPI`、`CN_PPI` 的 display/storage 口径
- 架构 grep 护栏，阻止旧模型和旧路由回流

## 7. 文档约束

活文档、页面说明、测试样例中，不得继续把旧 macro API、旧单位配置模型或硬编码单位映射写成推荐做法。历史说明应移入归档文档，而不是停留在开发主文档中。
