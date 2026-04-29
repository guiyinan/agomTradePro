# Macro Data Center Cutover

更新时间: 2026-04-29

## 目标

- `data_center_macro_fact` 成为宏观数据唯一事实表
- `IndicatorCatalog` 成为指标定义真源
- `IndicatorUnitRule` 成为量纲/单位规则真源
- `/api/macro/*` 正式退役，外部宏观 API 入口仅保留 `/api/data-center/*`
- 删除 `allow_legacy_fallback` 与 `LegacyMacroSeriesRepository`
- 旧 `macro_indicator` / `IndicatorUnitConfig` 不再作为运行时读写源

## 当前状态

- `apps/macro/application/repository_provider.py` 仍保留原 provider 入口
- `apps/macro/infrastructure/providers.py` 已切换为 `data_center` 兼容仓储
- `apps/macro/infrastructure/repositories.py` 已改为 `data_center_compat` shim，不再落回旧 ORM 仓储
- `apps/data_center/application/use_cases.py` 的宏观同步、查询与 repair 链路已移除 legacy fallback
- `apps/data_center/migrations/0007_expand_macro_indicator_catalog_coverage.py` 补齐了宏观 catalog 主指标覆盖，并统一 `CN_FX_RESERVES`
- `apps/data_center/migrations/0008_indicator_unit_rules.py` / `0009_rename_indicator_unit_rule_indexes.py` 已落地量纲规则表和索引修正
- `apps/macro/migrations/0018_drop_indicator_unit_config.py` 已删除旧 `IndicatorUnitConfig` 表

## 2026-04-30 量纲修复补充

- 利率/百分比类指标在 source payload 为 `3.0`、`1.243` 这类百分点时，系统统一按百分点存储和展示，`unit='%'` 不再隐式缩放为 `0.03`、`0.01243`
- 本轮已覆盖并验证 `CN_LPR`、`CN_SHIBOR`、`CN_RRR`、`CN_DR007`、`CN_UNEMPLOYMENT`、`CN_NEW_HOUSE_PRICE`
- 货币量纲已支持 `元/千元/万元/亿元/万亿元` 双向换算；canonical storage 继续统一到 `元`
- `normalize_macro_fact_units` 不只修数值和单位，也会回填 `matched_rule_id`、`display_unit`、`dimension_key`、`publication_lag_days` 等治理元信息
- 脏数据修复流程固定为：先修 fetcher / 规则，再走 `SyncMacroUseCase` 重刷事实，最后执行 `python manage.py normalize_macro_fact_units` 并要求 dry-run 为 `updated=0`

## 当前治理入口

- `GET/POST /api/data-center/indicators/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/`
- `GET/POST /api/data-center/indicators/{code}/unit-rules/`
- `GET/PATCH/DELETE /api/data-center/indicators/{code}/unit-rules/{rule_id}/`
- `GET /api/data-center/macro/series/`

所有前端展示单位应读取 `display_value + display_unit`，内部计算继续使用 canonical `value + unit`。

## 页面/API 收口说明

- `/api/macro/*` 已从 `core/urls.py` 卸载
- `core/templates/macro/data.html` 已改为直接读取 `/api/data-center/macro/series/`
- 宏观页面左侧指标列表改为读取 `IndicatorCatalog` 全量 active 目录，不再按 `MacroFact` distinct code 截断
- 对于目录中已治理但当前环境尚未同步事实数据的指标，页面显示“暂无同步数据”空态，而不是直接消失
- `/macro/data/` 现已支持“当前指标手动刷新抓取”：
  - 页面按钮直接调用 `POST /api/data-center/sync/macro/`
  - provider 仅从 Data Center active provider 解析，不再回落到旧 `macro` 同步链路
  - 页面会按指标周期给出建议抓取窗口：日频默认近 2 年，周频默认近 5 年，月/季/年频默认回溯到 `2010-01-01`
- `/macro/data/` 左栏滚动已收为单层：外层 sticky 容器不再滚动，指标列表成为唯一滚动区，分类展开区不再叠加内层滚动条
- `core/templates/regime/dashboard.html` 的手动同步已改走 `/api/data-center/sync/macro/`
- 旧宏观数据管理页 `/macro/controller/` 已重定向到 `/data-center/providers/`

## 刷新但不需要重训

- 宏观页面首屏上下文与图表缓存
- `/api/macro/table/`、`/api/macro/indicator-data/` 的服务端/边缘缓存
- 数据管理页统计卡片与最近同步记录
- 依赖宏观最新值的首页/策略说明页快照
- `decision_reliability` / `pulse` 页面上下文中的宏观 freshness 结果

## 不需要重训

- Qlib 训练产物
- Alpha 模型权重
- 因子训练快照
- 回测训练数据集本身

需要时只做数据刷新、快照重算和页面缓存失效，不做模型重训。
