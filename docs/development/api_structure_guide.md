# AgomTradePro 宏观 API 与 Data Center 结构指南

## 1. 当前唯一口径

自 2026-04 宏观链路收口后，系统的宏观数据只保留两类真源：

1. `IndicatorCatalog`：指标目录真源，管理代码、名称、分类、说明、默认周期等语义字段。
2. `IndicatorUnitRule`：量纲规则真源，管理 `source_type`、`original_unit`、`storage_unit`、`display_unit`、`multiplier_to_storage` 等规则。

宏观事实数据只存 `data_center_macro_fact`，外部读入口统一为：

- `GET/POST /api/data-center/publishers/`
- `GET/PATCH/DELETE /api/data-center/publishers/{code}/`
- `GET /api/data-center/macro/series/`
- `POST /api/data-center/sync/macro/`
- `GET/POST /api/data-center/indicators/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/`
- `GET/POST /api/data-center/indicators/{code}/unit-rules/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/`

旧 macro API 前缀、旧单位配置模型、硬编码单位映射与 legacy fallback 已退出运行时。

## 2. 宏观时序响应结构

`GET /api/data-center/macro/series/` 返回 canonical storage pair、display pair 与 provenance contract：

```json
{
  "indicator_code": "CN_GDP",
  "provenance_class": "official",
  "provenance_label": "官方数据",
  "publisher": "国家统计局",
  "publisher_code": "NBS",
  "publisher_codes": ["NBS"],
  "access_channel": "akshare",
  "chart_policy": "yearly_reset_bar",
  "chart_reset_frequency": "year",
  "chart_segment_basis": "period_delta",
  "derivation_method": "",
  "upstream_indicator_codes": [],
  "is_derived": false,
  "decision_grade": "decision_safe",
  "must_not_use_for_decision": false,
  "data": [
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
      "quality": "official",
      "provenance_class": "official",
      "provenance_label": "官方数据",
      "publisher": "国家统计局",
      "publisher_code": "NBS",
      "publisher_codes": ["NBS"],
      "access_channel": "akshare",
      "derivation_method": "",
      "is_derived": false
    }
  ]
}
```

字段约定：

- `value` + `unit`：系统内部计算口径，只表示 canonical storage value/unit。
- `display_value` + `display_unit`：页面、图表、表格统一展示口径。
- `original_unit`：数据源原始单位，供审计和巡检使用。
- `series_semantics`：指标的业务时序语义真源，例如 `yoy_rate`、`flow_level`、`cumulative_level`。
- `provenance_class`：宏观来源分类，只允许 `official`、`authoritative_third_party`、`derived`。
- `publisher`：原始发布/维护机构。
- `publisher_code`：主发布机构代码，供程序稳定引用。
- `publisher_codes`：联合发布机构代码列表。
- `access_channel`：系统访问通道，例如 `akshare`、`data_center`。
- `derivation_method`：仅衍生序列使用，说明派生逻辑。
- `upstream_indicator_codes`：仅衍生序列使用，列出上游真源指标。
- `decision_grade` + `must_not_use_for_decision`：是否允许直接进入决策链路。
- `chart_policy`：图表展示治理属性。当前 canonical 枚举为：
  - `continuous_line`：适用于同比/环比、利率、指数、余额等连续观察序列。
  - `period_bar`：适用于当期值、流量值等离散周期序列。
  - `yearly_reset_bar`：适用于年内累计值，跨年会自然重置，展示层不得直接连成连续趋势线。
- `chart_reset_frequency`：reset-stack 图表的重置频率，例如 `year`。
- `chart_segment_basis`：reset-stack 图表的分段口径；`period_delta` 表示同一重置周期内按相邻累计值差分后再分段展示。

运行时约束：

- `series_semantics` 是图表策略的一级真源，`chart_policy`、`chart_reset_frequency`、`chart_segment_basis` 是直接供 UI / MCP / SDK 消费的展示真源。
- 前端、MCP、SDK 不允许再按指标代码、周期类型或历史经验推断“是否适合连线”。
- 新环境或修库后建议执行：

```bash
python manage.py init_macro_indicator_governance --strict
```

当前宏观 provenance 约束：

1. `official`：官方原始统计或官方公开发布。
2. `authoritative_third_party`：权威机构维护，但不是国家统计口径本身。
3. `derived`：系统自动算出的衍生序列，默认 `research_only`。

典型例子：

- `CN_EXPORT_YOY`：`official`，来自海关总署当月出口同比增速。
- `CN_SHIBOR`：`authoritative_third_party`，来自全国银行间同业拆借中心。
- `CN_SOCIAL_FINANCING_YOY`：`derived`，由系统按同月社融增量同比派生，默认不可直接用于决策。

## 2.1 Publisher 代码表

为避免 `人民银行` / `中国人行` / `中国人民银行` 这类自由文本漂移，宏观 provenance 现在统一引入 `PublisherCatalog`：

- 单机构时使用 `publisher_code`
- 联合发布时使用 `publisher_codes`
- `publisher` 继续保留为展示文本，但程序逻辑应优先依赖 code

当前典型 canonical code：

- `NBS` = 国家统计局
- `CFLP` = 中国物流与采购联合会
- `GACC` = 海关总署
- `PBOC` = 中国人民银行
- `SAFE` = 国家外汇管理局
- `NIFC` = 全国银行间同业拆借中心
- `CFETS` = 中国外汇交易中心
- `SYSTEM_DERIVED` = 系统派生

## 3. 单位治理规则

规则匹配顺序固定为：

1. `indicator_code + source_type`
2. `indicator_code + source_type=""`

若仍匹配不到规则：

- 同步失败
- 写入审计
- 不允许回退到硬编码单位或 legacy 单位字典
- fetcher 直接 fail-closed，不允许本地 mock/fallback 单位继续出数

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
2. 显式写入 `series_semantics`，并让 `chart_policy` 由治理命令/迁移派生。
3. 在 `IndicatorUnitRule` 新建默认规则，必要时补 provider 覆盖规则。
4. 在对应 provider/fetcher 增加原始抓取逻辑。
5. 运行 `python manage.py init_macro_indicator_governance --strict`。
6. 跑同步。
7. 用 `/api/data-center/macro/series/` 验证 canonical/storage/display 三套字段是否正确。

禁止再做：

- 在代码里新增单位硬编码字典
- 在 `macro_indicator` 写入运行时事实
- 增加旧 macro API 兼容接口

## 8. 验收清单

- 运行时宏观事实只从 `data_center` 读取
- 页面不再展示错误标题、错误单位或错误说明
- 新指标可只通过 Admin/API 完成目录与量纲治理
- 除迁移与归档文档外，不再新增旧宏观 API 或旧单位模型引用
