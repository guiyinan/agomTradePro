# AgomTradePro 宏观 API 与 Data Center 结构指南

## 1. 当前唯一口径

自 2026-04 宏观链路收口后，系统的宏观数据只保留两类真源：

1. `IndicatorCatalog`：指标目录真源，管理代码、名称、分类、说明、默认周期等语义字段。
2. `IndicatorUnitRule`：量纲规则真源，管理 `source_type`、`original_unit`、`storage_unit`、`display_unit`、`multiplier_to_storage` 等规则。

宏观事实数据只存 `data_center_macro_fact`，外部读入口统一为：

- `GET /api/data-center/macro/series/`
- `POST /api/data-center/sync/macro/`
- `GET/POST /api/data-center/indicators/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/`
- `GET/POST /api/data-center/indicators/{code}/unit-rules/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/`

旧 macro API 前缀、旧单位配置模型、硬编码单位映射与 legacy fallback 已退出运行时。

## 2. 宏观时序响应结构

`GET /api/data-center/macro/series/` 返回 canonical storage pair 与 display pair：

```json
{
  "indicator_code": "CN_GDP",
  "series": [
    {
      "value": 134908400000000.0,
      "unit": "元",
      "display_value": 1349084.0,
      "display_unit": "亿元",
      "original_unit": "亿元",
      "reporting_period": "2025-12-31",
      "period_type": "Q",
      "published_at": "2026-01-17",
      "source": "akshare",
      "quality": "official"
    }
  ]
}
```

字段约定：

- `value` + `unit`：系统内部计算口径，只表示 canonical storage value/unit。
- `display_value` + `display_unit`：页面、图表、表格统一展示口径。
- `original_unit`：数据源原始单位，供审计和巡检使用。

## 3. 单位治理规则

规则匹配顺序固定为：

1. `indicator_code + source_type`
2. `indicator_code + source_type=""`

若仍匹配不到规则：

- 同步失败
- 写入审计
- 不允许回退到硬编码单位或 legacy 单位字典

示例：

```json
{
  "indicator_code": "CN_M2",
  "source_type": "akshare",
  "dimension_key": "money",
  "original_unit": "万亿元",
  "storage_unit": "元",
  "display_unit": "万亿元",
  "multiplier_to_storage": 1000000000000.0,
  "priority": 50,
  "is_active": true
}
```

## 4. 采集与入库流程

1. Provider 只负责抓取原始值与来源。
2. `SyncMacroUseCase` 在入库前查询 `IndicatorUnitRule`。
3. 以 `multiplier_to_storage` 计算 canonical storage value。
4. `data_center_macro_fact.value` 存 canonical value。
5. `data_center_macro_fact.unit` 存 canonical storage unit。
6. `extra.original_unit` 持久化原始单位。

因此：

- 页面展示永远使用 `display_*`
- 内部计算永远使用 `value/unit`
- 新增指标不再通过改代码补单位映射

## 5. 指标治理 API

### 5.1 指标 CRUD

```http
GET  /api/data-center/indicators/
POST /api/data-center/indicators/
GET  /api/data-center/indicators/{code}/
PATCH /api/data-center/indicators/{code}/
DELETE /api/data-center/indicators/{code}/
```

指标字段：

- `code`
- `name_cn`
- `name_en`
- `description`
- `category`
- `default_period_type`
- `is_active`
- `extra`

### 5.2 量纲规则 CRUD

```http
GET  /api/data-center/indicators/{code}/unit-rules/
POST /api/data-center/indicators/{code}/unit-rules/
GET  /api/data-center/indicators/{code}/unit-rules/{rule_id}/
PATCH /api/data-center/indicators/{code}/unit-rules/{rule_id}/
DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/
```

规则字段：

- `source_type`
- `dimension_key`
- `original_unit`
- `storage_unit`
- `display_unit`
- `multiplier_to_storage`
- `is_active`
- `priority`
- `description`

## 6. 页面与前端约束

所有页面、图表、表格统一遵循：

1. 只从 `/api/data-center/macro/series/` 读取宏观数据。
2. 标题和说明文案使用 `IndicatorCatalog` 语义字段。
3. 数值显示使用 `display_value + display_unit`。
4. 宏观指标选择器优先读取 `IndicatorCatalog` active 目录，而不是按事实表已落库 code 裁剪。
5. 对于目录已存在但事实表暂未同步的指标，前端必须展示明确空态，不得隐藏或报错。
6. 不再展示或拼接旧 macro API 路径。

## 7. 新增指标的正确流程

新增一个宏观指标时，只允许做以下动作：

1. 在 `IndicatorCatalog` 新建指标。
2. 在 `IndicatorUnitRule` 新建默认规则，必要时补 provider 覆盖规则。
3. 在对应 provider/fetcher 增加原始抓取逻辑。
4. 跑同步。
5. 用 `/api/data-center/macro/series/` 验证 canonical/storage/display 三套字段是否正确。

禁止再做：

- 在代码里新增单位硬编码字典
- 在 `macro_indicator` 写入运行时事实
- 增加旧 macro API 兼容接口

## 8. 验收清单

- 运行时宏观事实只从 `data_center` 读取
- 页面不再展示错误标题、错误单位或错误说明
- 新指标可只通过 Admin/API 完成目录与量纲治理
- 除迁移与归档文档外，不再新增旧宏观 API 或旧单位模型引用
