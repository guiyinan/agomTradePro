# Macro Data Center Cutover

更新时间: 2026-07-19

## 目标

- `data_center_macro_fact` 成为宏观数据唯一事实表
- `IndicatorCatalog` 成为指标定义真源
- `IndicatorUnitRule` 成为量纲/单位规则真源
- `/api/macro/*` 正式退役，外部宏观 API 入口仅保留 `/api/data-center/*`
- 删除 `allow_legacy_fallback` 与 `LegacyMacroSeriesRepository`
- 旧 `macro_indicator` / `IndicatorUnitConfig` 不再作为运行时读写源

## 当前状态

- Macro 的生产同步入口仅保留 Application facade，实际批量同步由 Data Center 的 canonical `ProviderRegistry` 选择 provider
- Tushare / AKShare / failover 宏观采集实现已迁入 `apps/data_center/infrastructure/macro_sources/`
- `apps/macro/infrastructure/adapters.py`、`adapters/`、`providers.py`、`repositories.py` 与 `data_center_compat.py` 已退役
- Macro 对 canonical fact 的领域映射集中在 `data_center_fact_repository.py`，不再存在多层 re-export shim
- `apps/data_center/application/use_cases.py` 的宏观同步、查询与 repair 链路已移除 legacy fallback
- `apps/data_center/migrations/0007_expand_macro_indicator_catalog_coverage.py` 补齐了宏观 catalog 主指标覆盖，并统一 `CN_FX_RESERVES`
- `apps/data_center/migrations/0008_indicator_unit_rules.py` / `0009_rename_indicator_unit_rule_indexes.py` 已落地量纲规则表和索引修正
- `apps/macro/migrations/0018_drop_indicator_unit_config.py` 已删除旧 `IndicatorUnitConfig` 表

## 2026-07-18 provider / adapter 抽象收敛

- `ProviderRegistry` 成为 provider 构造、ID/名称查找、能力路由、failover、熔断和运行时健康状态的唯一 owner。
- 删除 Data Center 的 `provider_factory.py`、`providers.py` 与 `registries/source_registry.py`；Application composition 不再维护伪 provider 或重复 capability 映射。
- 市场站点客户端统一称为 internal market gateway，并使用 `MarketGatewayProtocol`，与外部数据 provider 注册机制明确分层。
- `build_sync_macro_data_use_case()` 不再组装旧 adapter 字典，改为委托 `SyncMacroBatchUseCase`；管理命令也走同一 canonical 同步入口。
- 结构测试固定检查旧路径不得恢复，运行回归覆盖 provider registry、macro source、同步、fact projection 及跨模块消费者。

## 2026-07-19 MacroFact 治理闭环

- `MacroFactGovernanceNormalizer` 是事实写入前的统一治理入口，负责 catalog 存在性、单位规则、canonical value/unit、source、original/display unit、dimension、multiplier、matched rule、period type 与 publication lag。
- `SyncMacroUseCase`、市场温度计同步、市场新闻派生指标、ETF 多源共识和投资者账户导入均走该入口；`MacroFactRepository` 会拒绝缺少治理元数据的旁路写入。
- Equity 指数行情只写 `PriceBar`，不再把指数点位重复镜像为未登记的宏观指标。
- 迁移 `0033_close_macro_fact_governance_gaps` 补齐晚于治理迁移创建的 ETF 指标元数据，统一期限利差为 BP，并批量回填历史事实治理字段；期限利差旧 `%` 标签只改为 `BP`，不改变已存数值。
- 冷启动会修复 indicator metadata；VPS 发布在切换版本前执行以下只读漂移门禁，任一不为零即中止发布：

```bash
python manage.py init_macro_indicator_governance --check
python manage.py normalize_macro_fact_units --check
```

- `normalize_macro_fact_units` 已改为预加载规则和批量更新，避免逐事实查询和逐行保存。

## 2026-04-30 量纲修复补充

- 利率/百分比类指标在 source payload 为 `3.0`、`1.243` 这类百分点时，系统统一按百分点存储和展示，`unit='%'` 不再隐式缩放为 `0.03`、`0.01243`
- 本轮已覆盖并验证 `CN_LPR`、`CN_SHIBOR`、`CN_RRR`、`CN_DR007`、`CN_UNEMPLOYMENT`、`CN_NEW_HOUSE_PRICE`
- 货币量纲已支持 `元/千元/万元/亿元/万亿元` 双向换算；canonical storage 继续统一到 `元`
- `normalize_macro_fact_units` 不只修数值和单位，也会回填 `matched_rule_id`、`display_unit`、`dimension_key`、`publication_lag_days` 等治理元信息
- 脏数据修复流程固定为：先修 fetcher / 规则，再走 `SyncMacroUseCase` 重刷事实，最后执行 `python manage.py normalize_macro_fact_units` 并要求 dry-run 为 `updated=0`

## 2026-07-19 Regime CPI 读取口径修复

- `CN_CPI_NATIONAL_YOY` 的 canonical storage unit 是 `%`，数值直接表示百分比点；例如 `0.1` 表示 `0.1%`，读取链不得再按数值大小猜测口径并乘以 100。
- 同一约束同时覆盖 `apps/macro` 的 Data Center fact repository projection 与 `apps/regime` 的 V2 macro adapter；两条读取链都必须有小正值、小负值和 legacy base-100 回归测试，防止兼容层重复缩放。
- 只有 legacy `CN_CPI` 基准指数需要执行 `value - 100` 转换。来源若返回小数比例，必须在 Data Center unit rule 中显式配置 multiplier，不得在 Regime 投影层做启发式缩放。
- Regime current API 现在透传 V2 计算得到的 PMI/CPI 当前值及方向，MCP/SDK 不再用 `neutral` 和空值填补缺失字段。
- `regime.compute.calculate` 已由 Regime ViewSet 显式标记为 persisted-only read action，因此只读 Token 可以调用该 POST transport；未显式标记的 POST 仍按写操作拒绝。
- 生产刷新顺序固定为：同步 `CN_PMI` 与 `CN_CPI_NATIONAL_YOY`、清除 Regime 缓存、用 MCP 同时核对 canonical macro series 与 Regime raw data。
- `MacroFactRepository.bulk_upsert` 在更新已有自然键时必须同步写入本次 provider fetch 的 `fetched_at`；否则值虽已刷新，新鲜度与审计读取仍会错误沿用首次入库时间。
- 旧宏观仓储的 `save_indicator` 更新路径同样必须推进 `fetched_at`，避免兼容入口形成另一条时间戳滞留路径。
- 切换前的宏观仓储曾把首条记录写成 revision 1，而 canonical Data Center 从 revision 0 开始；Regime 去重时优先选择带 `provider_name` 治理元数据的 canonical fact，防止旧 revision 遮住本次刷新值。
- Data Center 宏观序列查询按 `reporting_period + source` 去重，保留多来源可审计性，但同一来源同一期只返回一个 canonical fact。

## 2026-05-03 宏观治理台与口径补齐

- 新增 staff 治理页 `/data-center/governance/`，用于集中审计：
  - legacy `source` 别名残留
  - catalog-only 缺口
  - 可自动补同步缺口
  - 配对序列缺失
- 本轮已完成 `AKShare Public -> akshare` 存量统一，治理台当前不再报 `legacy source` 问题。
- 本轮已补齐并回填：
  - `CN_FIXED_INVESTMENT`
  - `CN_FAI_YOY`
  - `CN_SOCIAL_FINANCING`
  - `CN_SOCIAL_FINANCING_YOY`
  - `CN_EXPORT_YOY`
  - `CN_IMPORT_YOY`
- 进出口 canonical 语义已纠正：
  - `CN_EXPORTS` / `CN_IMPORTS` = 当月金额口径，display unit `亿美元`
  - `CN_EXPORT_YOY` / `CN_IMPORT_YOY` = 当月金额同比增速
- `CN_CPI_YOY` 当前只保留为兼容 alias；治理真源优先读 `CN_CPI_NATIONAL_YOY`
- 截至 `2026-05-03`，治理台真实缺口已清零，只剩兼容 alias 提示项。
- `apps/macro/application/indicator_service.py` 中已移除 `CN_EXPORT_YOY -> CN_EXPORTS`、`CN_IMPORT_YOY -> CN_IMPORTS`、`CN_RETAIL_SALES_YOY -> CN_RETAIL_SALES` 这类危险回退，避免同比指标再被误映射到绝对额序列。

## 2026-05-03 运行配置下沉补充

- `IndicatorCatalog.extra` 已补齐并开始承载以下运行时元数据：
  - `schedule_frequency`
  - `schedule_day_of_month`
  - `schedule_release_months`
  - `publication_lag_days`
  - `publication_lag_description`
  - `orm_period_type_override`
  - `domain_period_type_override`
- `ScheduleDataFetchUseCase` 的宏观调度口径现完全读取 catalog runtime metadata，本地已不再维护独立同步日历表。
- `sync_macro_data` 的 period_type 解析现完全读取 catalog period override / source payload，本地已不再维护 legacy period override 表。
- `apps/data_center/infrastructure/macro_sources/fetchers/*` 现优先读取 runtime metadata / unit rule 解析 source unit。
- 对所有宏观指标，若 runtime metadata 与 active unit rule 都缺失，则 fetcher 现在一律 fail-closed。
- 本地 `INDICATOR_UNITS` / `allow_fetcher_unit_fallback` 已退出运行时，不再允许任何白名单 fallback。
- `apps/data_center/infrastructure/macro_sources/base.py` 的发布时间 lag 现完全读取 runtime publication lag metadata，本地已不再维护发布日期 lag 常量表。
- 季度调度已补上真实判定逻辑，不再出现配置了 `quarterly` 但运行时永远不触发的情况。
- 宏观治理台巡检范围也已下沉到 `IndicatorCatalog.extra`：
  - `governance_scope`
  - `governance_sync_supported`
  - `governance_sync_source_type`
- `MacroGovernanceRepository` 现根据 catalog metadata 构建治理清单，不再依赖页面层硬编码指标列表。
- 治理台的“补同步缺失序列”动作现通过 `RunMacroGovernanceActionUseCase + SyncMacroUseCase` 执行，并按 `governance_sync_source_type` 选择 provider；页面层不再硬编码 `akshare`。
- legacy `source` 统一也已改为运行时推断：
  - 优先使用 `data_center_macro_fact.extra.source_type`
  - 否则回退到 `ProviderConfig(name -> source_type)` 映射
- 因此治理台与修复动作不再维护独立 `AKShare Public -> akshare` 这类页面层 alias 表。
- `apps/data_center/migrations/0017_canonicalize_fact_sources.py` 已完成 Data Center 全量事实表 `source` 存量整改：
  - 统一将事实表 `source` 规范为 canonical `source_type`
  - 对带 `extra` 的事实保留 `extra.provider_name` 与 `extra.source_type` 供审计使用
- `apps/data_center/migrations/0018_seed_macro_compat_alias_catalog.py` 已将剩余 legacy 指标别名下沉到 catalog：
  - `CN_PMI_MANUFACTURING -> CN_PMI`
  - `CN_PMI_NON_MANUFACTURING -> CN_NON_MAN_PMI`
  - `CN_CPI_MOY -> CN_CPI_NATIONAL_MOM`
  - `CN_CPI_YOY -> CN_CPI_NATIONAL_YOY`
- `apps/macro/application/indicator_service.py` 已删除本地 `LEGACY_CODE_ALIASES` 常量；兼容码解析现完全依赖 catalog alias metadata。
- 后续 Data Center 同步写入也已统一：
  - 事实表 `source` 固定写 canonical `source_type`
  - provider 展示名仅保留在审计日志与 `extra.provider_name`

## 2026-05-04 provenance 与护栏补充

- `PublisherCatalog` 已落地为 provenance 机构代码表，用于归一机构别名：
  - `人民银行` / `中国人行` / `中国人民银行` -> `PBOC`
  - `统计局` / `国家统计局` -> `NBS`
- `IndicatorCatalog.extra` 的 publisher 相关字段现统一为：
  - `publisher`
  - `publisher_code`
  - `publisher_codes`
- `GET /api/data-center/macro/series/` 现统一返回 provenance contract：
  - `provenance_class`
  - `provenance_label`
  - `publisher`
  - `publisher_code`
  - `publisher_codes`
  - `access_channel`
  - `derivation_method`
  - `upstream_indicator_codes`
  - `is_derived`
  - `decision_grade`
  - `must_not_use_for_decision`
- provenance 当前只允许三类：
  - `official`
  - `authoritative_third_party`
  - `derived`
- `derived` 序列默认只能 `research_only`，即使 freshness 为 `fresh`，也不得直接进入决策链路。
- 已补种子元数据示例：
  - `CN_EXPORT_YOY` = `official`，发布方 `海关总署`
  - `CN_SHIBOR` = `authoritative_third_party`，发布方 `全国银行间同业拆借中心`
  - `CN_SOCIAL_FINANCING_YOY` = `derived`，发布方 `系统派生`
- `CN_EXPORT_YOY` 在 `2021-02` 出现 `154.9%` 属于低基数下的官方同比值，不是单位转换错误。
- `CN_SOCIAL_FINANCING_YOY` 已明确标成系统衍生，并增加 `prior_flow_value > 0` 护栏，避免负基数/零基数把同比结果炸穿。

## 仍保留的运行默认常量

- 当前宏观治理链路里已不再保留额外的代码内 alias / schedule / publication lag / period override 真源表。
- 业务口径、单位、配对关系、compat alias、canonical storage 统一以 `IndicatorCatalog`、`IndicatorUnitRule`、`data_center_macro_fact` 为准。

## 当前治理入口

- `GET /data-center/publishers/`
- `GET /data-center/providers/`
- `GET /data-center/monitor/`
- `GET/POST /api/data-center/publishers/`
- `GET/PATCH/DELETE /api/data-center/publishers/{code}/`
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
- `/macro/data/` 现已支持“当前指标一次性自动自愈刷新”：
  - 当指标 `sync_supported=true` 且当前状态为 `stale/degraded`，页面会自动补抓一次
  - 当指标目录已接入治理但当前环境尚无事实数据时，页面也会自动补抓一次
  - 自动刷新只对每个指标触发一次，避免页面轮询式反复打源
- `/macro/data/` 左栏滚动已收为单层：外层 sticky 容器不再滚动，指标列表成为唯一滚动区，分类展开区不再叠加内层滚动条
- `core/templates/regime/dashboard.html` 的手动同步已改走 `/api/data-center/sync/macro/`
- 旧宏观数据管理页 `/macro/controller/` 已重定向到 `/data-center/providers/`

## 2026-05-07 freshness 自愈补充

- `apps/macro/application/tasks.check_data_freshness` 已改为 catalog 驱动：
  - 不再硬编码 `PMI/CPI/M2/PPI`
  - 统一扫描 `IndicatorCatalog.extra.governance_sync_supported=true` 的 active 指标
  - 缺失序列与 stale 序列都会被纳入告警结果
- 新增 `apps.macro.application.tasks.auto_sync_due_macro_indicators`：
  - 自动识别 `missing/stale` 的治理指标
  - 按 `governance_sync_source_type` 选择 active provider
  - 按指标周期和最新报告期自动推断回补窗口
- `CELERY_BEAT_SCHEDULE` 已加入 `auto-sync-due-macro-indicators`，每天 `08:20` 自动执行一次，配合现有 freshness 巡检，形成“检查 + 自动补抓”的数据基座闭环。

## 2026-05-07 direct-input 护栏补充

- `IndicatorCatalog.extra` 现统一补齐：
  - `regime_input_policy`
  - `pulse_input_policy`
- 当前通用策略：
  - `series_semantics = cumulative_level` => `derive_required`
  - 其他已治理语义默认 => `direct_allowed`
- `apps/regime/infrastructure/macro_data_provider.py` 现会在增长/通胀输入侧拦截 `derive_required` 指标，避免把年内累计值直接送入 Regime 动量计算。
- `apps/pulse/infrastructure/data_provider.py` 现会在 Pulse 宏观读数入口拦截 `derive_required` 指标，避免把跨年重置的累计值直接拿去做 `zscore / level / pct_change`。
- 这意味着像 `CN_GDP`、`CN_FIXED_INVESTMENT`、`CN_INDUSTRIAL_PROFIT` 这类累计口径序列，只能先转换为同比、环比、单期增量或其他明确派生口径，再用于决策链路。

## 2026-05-11 金融月频报告期修复

- 金融类 AKShare fetcher 的中文月份解析已与基础宏观 fetcher 对齐：`2026年3月` 统一解析为 `2026-03-31`，不再落到月初。
- 该修复会让 `CN_NEW_CREDIT` 等月频金融指标的 `published_at = reporting_period + publication_lag_days` 落到真实的次月发布窗口，避免 Pulse freshness 误把尚在有效窗口内的新增信贷判为 stale。
- `repair_decision_data_reliability` 管理命令已补齐 `IndicatorUnitRuleRepository` 注入，手动修复链路可继续执行 macro sync、quote sync 与 Pulse 复验。

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

## 2026-07-20 数值一致性根因与护栏

- CPI 明细抓取不再按 Python 值类型分支缩放：字符串 `"1.0%"` 与数值 `1.0` 统一解析为 `1.0` 个百分点，避免上游 DataFrame dtype 变化造成 100 倍漂移。
- 单位治理只允许“原始单位精确匹配”或“原始单位等于存储单位”的规则；未知原始单位不再猜测套用其他倍率规则。
- canonical 事实以 `extra.provider_name` 标记优先于切换前 legacy revision；revision 只在同一写入体系内表示修订顺序，不能跨体系覆盖 canonical 数据。
- Regime、Pulse、Filter、Data Center 查询仓储、缓存预热以及 legacy macro projection 统一走同一个事实选择器：
  - 同一来源同一报告期先去重；
  - 有 `governance_sync_source_type` / `decision_source_type` 时只读治理来源；
  - 未配置来源时，重叠数据必须在 1% 容差内一致；
  - 超过容差立即返回不可用，不再跨来源拼接时间序列。
- failover 一致性比较改为对称相对误差，`0` 对 `非 0` 也会失败，不再因除零保护被静默跳过。
- `CN_A_TOTAL_TURNOVER` 原实现把上证综指与深证成指成交额之和当作“全市场成交额”，指标名称与代理口径不一致。现改为：
  - Tushare：按交易日汇总全部 A 股日线 `amount`；
  - AKShare：汇总上交所主板 A/科创板与深交所 A 股官方市场概况；
  - 指数成交额 fallback 因语义不等价而 fail closed；
  - `IndicatorCatalog.extra.decision_source_type=tushare` 作为决策读取真源。
- 新增部署/巡检命令：

```bash
python manage.py audit_macro_fact_consistency --strict
```

命令同时报告 legacy/canonical 值冲突、跨来源差异和治理来源缺失；`--strict` 会阻断未配置来源的跨源冲突以及治理来源缺失。正常的同源数据修订不会被误报为 legacy/canonical 冲突。
